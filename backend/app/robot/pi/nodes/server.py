#!/usr/bin/env python3
"""Minimal robot server (Pi side) — body commands only.

A stripped-down replacement for ``robot_server.py``: the single job is to
accept raw servo commands over HTTP, execute them on the hardware, and return
when the motion is done. No vision, no classifier, no named motions.

Endpoints
    POST /move    execute raw servo commands (blocks until the body finishes)
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
    11: (428, 515),   # l_hip_yaw   — tightened to the bucket-stance span (out=428, in=512)
    12: (485, 572),   # r_hip_yaw   — mirror of servo 11 about stand=500 (in=488, out=572)
    13: (333, 835),   # l_sho_pitch — stand=835 (at ceiling)
    14: (165, 773),   # r_sho_pitch — widened from 200 to include stand=165
    15: (440, 830),   # l_sho_roll  — widened from 800 to include stand=830
    16: (170, 613),   # r_sho_roll  — widened from 213 to include stand=170
    17: (440, 653),   # l_el_pitch
    18: (320, 560),   # r_el_pitch
    19: (90, 360),    # l_el_yaw
    20: (573, 880),   # r_el_yaw DAMAGED — never command below 360
}

MIN_MOVE_MS = 100  # floor for any single move duration


def clamp_position(servo_id: int, position: int) -> int:
    lo, hi = SERVO_LIMITS.get(servo_id, (0, 1000))
    return max(lo, min(hi, int(position)))


# ── ROS plumbing ──────────────────────────────────────────────────────────────
_body_srv = None
_BodyCommandReq = None

# One motion at a time: overlapping motor commands fight each other, so a
# second /move while one is playing gets a 429 instead of a hardware lock.
_move_lock = threading.Lock()


def _init_ros() -> None:
    global _body_srv, _BodyCommandReq

    import rospy

    rospy.init_node("robot_server", anonymous=True, disable_signals=True)

    from ainex_demo.srv import BodyCommand, BodyCommandRequest  # type: ignore

    _BodyCommandReq = BodyCommandRequest
    rospy.loginfo("[server] waiting for /body_commands service...")
    rospy.wait_for_service("/body_commands", timeout=60.0)
    _body_srv = rospy.ServiceProxy("/body_commands", BodyCommand)
    rospy.loginfo("[server] ROS ready — body service wired")


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
    by_duration: Dict[int, Dict[str, int]] = {}
    for m in moves:
        name = ID_TO_NAME.get(m.servo_id)
        if name is None or m.servo_id in _SKIP_SERVO_IDS:
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


def main():
    port = int(os.getenv("AGENT_PORT", "9000"))
    print(f"[server] starting on 0.0.0.0:{port}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
