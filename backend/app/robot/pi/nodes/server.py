#!/usr/bin/env python3
"""Minimal robot server (Pi side) — body commands only.

A stripped-down replacement for ``robot_server.py``: the single job is to
accept raw servo commands over HTTP, execute them on the hardware, and return
when the motion is done. No vision, no classifier, no named motions.

Endpoints
    POST /move    execute raw servo commands (blocks until the body finishes).
                  While the robot marches, leg and arm servos are dropped (the
                  walking engine moves them, arms swinging with the steps).
    POST /walk    march with Hiwonder's walking engine {step_height m,
                  direction +1/0/-1}; must be renewed within
                  walking.KEEPALIVE_TIMEOUT_S or it stops. Steps forward or
                  back only by `direction`, 1 cm per step, at most
                  walking.MAX_TRAVEL_M from the start; never turns (only the
                  gyro heading hold, against drift).
    POST /walk/stop  stop marching; legs ease back to stand
    GET  /walk/status  {available, state, yaw_deg}
    GET  /imu     raw Board().get_imu() floats (accel g, gyro deg/s, mag), read-only
    GET  /health  liveness probe

Mirrors the Mac-side ``coral_agent/server.py`` /move contract: the request
body is a JSON list of ``{servo_id, position, duration_ms}`` objects. Each
position is a hardware pulse (0-1000), clamped to that servo's safe range
before dispatch. Execution goes through the blocking ROS ``/body_commands``
service (see ``body.py``), so the HTTP response returns only after every
frame has played.

Run inside the robot's ROS environment:
    source /home/ubuntu/ros_ws/devel/setup.bash
    python3 server.py

Environment variables:
    AGENT_PORT   HTTP port (default: 9000)
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Tuple

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Servo identity ────────────────────────────────────────────────────────────
SERVO_ID: Dict[str, int] = {
    "l_ank_roll": 1,   "r_ank_roll": 2,
    "l_ank_pitch": 3,  "r_ank_pitch": 4,
    "l_knee": 5,       "r_knee": 6,
    "l_hip_pitch": 7,  "r_hip_pitch": 8,
    "l_hip_roll": 9,   "r_hip_roll": 10,
    "l_hip_yaw": 11,   "r_hip_yaw": 12,
    "l_sho_pitch": 13, "r_sho_pitch": 14,
    "l_sho_roll": 15,  "r_sho_roll": 16,
    "l_el_pitch": 17,  "r_el_pitch": 18,
    "l_el_yaw": 19,    "r_el_yaw": 20,
    "l_gripper": 21,   "r_gripper": 22,
    "head_pan": 23,    "head_tilt": 24,
}
ID_TO_NAME: Dict[int, str] = {v: k for k, v in SERVO_ID.items()}

# Head servos are driven by the head node — never command them from here.
_SKIP_SERVO_IDS = {23, 24}

# Physical servo safety limits (override the 0-1000 default for constrained
# servos). MUST match hardware_angle_utils.HW_SERVO_LIMITS on the Mac — the
# sim's JOINT_LIMITS are derived from that table, so any drift here makes the
# hardware clamp differently than the sim predicts. Every range contains its
# servo's stand pulse, so the stand pose is never clamped. This is the ONLY
# clamp on the Pi: body.py deliberately does not re-clamp (see pulse_to_servos
# there), so this table is the single hardware source of truth.
SERVO_LIMITS: Dict[int, Tuple[int, int]] = {
    1:  (400, 600),   # l_ank_roll
    2:  (400, 600),   # r_ank_roll
    3:  (620, 720),   # l_ank_pitch — stand=640; 720 = crouch lean (dab/stand_low)
    4:  (280, 380),   # r_ank_pitch — stand=360; 280 = crouch lean (dab/stand_low)
    5:  (440, 760),   # l_knee      — conservative, stand=500
    6:  (240, 560),   # r_knee      — conservative, stand=500
    7:  (150, 450),   # l_hip_pitch — conservative, stand=350
    8:  (550, 850),   # r_hip_pitch — conservative, stand=650
    9:  (400, 600),   # l_hip_roll  — user-tested: 400=outward 30°, 600=inward 20°
    10: (400, 600),   # r_hip_roll  — user-tested: 400=inward 20°, 600=outward 30°
    # l/r_hip_yaw (11/12) and l/r_el_pitch (17/18) are the wire-twist rotation
    # joints (see backend/app/robot/robot_params.py's docstring). 2026-09-12:
    # relaxed from the bucket-stance-tuned span below to (100, 900) to mirror
    # that file's JOINT_SAFE_RANGES, at the user's request. PLACEHOLDER —
    # verify on hardware before an unattended demo.
    11: (100, 900),   # l_hip_yaw   — was (428, 515), tightened to the bucket-stance span
    12: (100, 900),   # r_hip_yaw   — was (485, 572), mirror of servo 11 about stand=500
    13: (333, 835),   # l_sho_pitch — stand=835 (at ceiling)
    14: (165, 773),   # r_sho_pitch — widened from 200 to include stand=165
    15: (440, 830),   # l_sho_roll  — widened from 800 to include stand=830
    16: (170, 613),   # r_sho_roll  — widened from 213 to include stand=170
    17: (100, 900),   # l_el_pitch  — was (440, 653), relaxed 2026-09-12 (see above)
    18: (100, 900),   # r_el_pitch  — was (320, 560), relaxed 2026-09-12 (see above)
    19: (90, 360),    # l_el_yaw
    20: (573, 880),   # r_el_yaw DAMAGED — never command below 360
}

MIN_MOVE_MS = 100  # floor for any single move duration
# Legs and arms — the walking engine's while it marches (it swings the arms).
_MARCH_SERVO_IDS = frozenset(range(1, 23))


def clamp_position(servo_id: int, position: int) -> int:
    lo, hi = SERVO_LIMITS.get(servo_id, (0, 1000))
    return max(lo, min(hi, int(position)))


# ── ROS plumbing ──────────────────────────────────────────────────────────────
_body_srv = None
_BodyCommandReq = None
_walker = None  # walking.Walker — None if the walking engine is unavailable
_board = None  # walking.LatestImu over ainex_sdk.Board — None if unavailable

# One motion at a time: overlapping motor commands fight each other, so a
# second /move while one is playing gets a 429 instead of a hardware lock.
_move_lock = threading.Lock()


def _init_ros() -> None:
    global _body_srv, _BodyCommandReq, _walker, _board

    import rospy

    rospy.init_node("robot_server", anonymous=True, disable_signals=True)

    from ainex_demo.srv import BodyCommand, BodyCommandRequest  # type: ignore

    _BodyCommandReq = BodyCommandRequest
    rospy.loginfo("[server] waiting for /body_commands service...")
    rospy.wait_for_service("/body_commands", timeout=60.0)
    _body_srv = rospy.ServiceProxy("/body_commands", BodyCommand)
    rospy.loginfo("[server] ROS ready — body service wired")

    # Walking is optional: without the engine, /walk reports 503 and /move
    # works exactly as before.
    # The IMU is optional too: without it the march runs without heading hold.
    try:
        from ainex_sdk import Board  # type: ignore
        from walking import LatestImu

        board = Board()
        board.enable_reception()
        _board = LatestImu(board.get_imu)   # the ONLY get_imu() caller
        threading.Thread(target=_board.run, name="imu-reader", daemon=True).start()
        rospy.loginfo("[server] IMU board ready")
    except Exception as e:
        rospy.logwarn(f"[server] IMU board unavailable, marching without heading hold: {e}")

    try:
        from walking import (LEG_STAND_PULSE, STAND_MS, RosWalkingEngine, Walker,
                             yaw_rate_from_imu)

        def stand_legs() -> None:
            with _move_lock:
                _call_body_service([(dict(LEG_STAND_PULSE), STAND_MS)])

        imu = _board
        yaw_rate = (lambda: yaw_rate_from_imu(imu.latest())) if imu is not None else None
        _walker = Walker(RosWalkingEngine(), stand_legs, yaw_rate=yaw_rate)
        threading.Thread(target=_walker.watch, name="walk-watchdog", daemon=True).start()
        rospy.loginfo("[server] walking engine ready (POST /walk)")
    except Exception as e:
        rospy.logwarn(f"[server] walking engine unavailable, /walk will report so: {e}")


def _call_body_service(
    sequence: List[Tuple[Dict[str, int], int]],
    global_duration: Optional[float] = None,
) -> float:
    """Send one (pulse_dict, duration_ms) sequence to the body node, blocking."""
    if _body_srv is None or _BodyCommandReq is None:
        raise RuntimeError("body service not initialized")
    commands_json = json.dumps([[pulse, dur] for pulse, dur in sequence])
    req = _BodyCommandReq(
        commands_json=commands_json,
        global_duration=float(global_duration or 0.0),
    )
    resp = _body_srv(req)
    return getattr(resp, "duration_ms", sum(dur for _, dur in sequence))


# ── FastAPI app ───────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_ros()
    yield


app = FastAPI(title="AiNex Robot Server (minimal)", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ServoMove(BaseModel):
    servo_id: int
    position: int
    duration_ms: int


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/move")
async def move(moves: List[ServoMove]):
    """Execute raw servo commands on the hardware; return when done.

    Moves sharing a duration are batched into one frame so they run
    simultaneously; distinct durations become successive frames the body node
    plays back-to-back. Every position is clamped to its servo's safe range.
    """
    # Group into (pulse_dict, duration) frames, matching the body service's
    # input shape. Unknown and head servo ids are silently dropped.
    if _walker is not None:
        _walker.note_body_motion()
    legs_walking = _walker is not None and _walker.legs_busy
    by_duration: Dict[int, Dict[str, int]] = {}
    for m in moves:
        name = ID_TO_NAME.get(m.servo_id)
        if name is None or m.servo_id in _SKIP_SERVO_IDS:
            continue
        if legs_walking and m.servo_id in _MARCH_SERVO_IDS:
            continue
        dur = max(MIN_MOVE_MS, m.duration_ms)
        by_duration.setdefault(dur, {})[name] = clamp_position(m.servo_id, m.position)

    sequence = [(pulse, dur) for dur, pulse in by_duration.items()]
    if not sequence:
        return {"status": "done", "count": 0}

    if not _move_lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="robot busy: a move is already executing")
    try:
        # The body service blocks until the whole sequence has played, so this
        # response returning is the "motion finished" signal.
        await asyncio.get_event_loop().run_in_executor(None, lambda: _call_body_service(sequence))
    finally:
        _move_lock.release()

    return {"status": "done", "count": sum(len(p) for p in by_duration.values())}


class WalkRequest(BaseModel):
    step_height: float = 0.02
    direction: int = 0   # +1 forward, -1 backward, 0 in place


@app.post("/walk")
def walk(req: WalkRequest):
    """Start marching in place, or renew a march. The laptop
    must keep calling this or the march stops by itself. Not held up by a
    /move in progress: follow mode keeps moving the arms while marching."""
    if _walker is None:
        raise HTTPException(status_code=503, detail="walking engine not available")
    from walking import WalkerBusy

    try:
        settings = _walker.walk(req.step_height, req.direction)
    except WalkerBusy as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"walking": True, **settings}


@app.post("/walk/stop")
def walk_stop():
    if _walker is not None:
        _walker.stop()
    return {"walking": False}


@app.get("/walk/status")
def walk_status():
    from walking import MAX_TRAVEL_M

    if _walker is None:
        return {"available": False, "state": "idle", "yaw_deg": None}
    return {"available": True, "state": _walker.state, "yaw_deg": round(_walker.yaw_deg, 1),
            "travel_m": round(_walker.travel_m, 3),
            "max_travel_m": MAX_TRAVEL_M,
            "last_stop_s": _walker.last_stop_s}


@app.get("/imu")
def imu():
    """Raw floats from Board().get_imu(): accel (g) x,y,z, gyro (deg/s)
    x,y,z, magnetometer x,y,z. None values = the board didn't answer this
    call (routine; retry)."""
    if _board is None:
        raise HTTPException(status_code=503, detail="IMU board not initialized")
    values = _board.latest()
    return {"values": values}


def main():
    port = int(os.getenv("AGENT_PORT", "9000"))
    print(f"[server] starting on 0.0.0.0:{port}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
