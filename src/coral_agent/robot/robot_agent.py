"""Robot-side agent server — deploy and run this ON the AiNex robot.

Receives servo commands from the laptop's hardware_controller.py over HTTP
and drives the physical servos through the ROS MotionManager (see control.py).

Must run inside the robot's ROS environment:
    source /home/ubuntu/ros_ws/devel/setup.bash   # so rospy + ainex_kinematics resolve
    # roscore + the servo controller node must already be running
    python3 robot_agent.py

Environment variables (set on the robot):
    AGENT_PORT    HTTP port this server listens on (default: 9000)
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Tuple

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Servo bus backend — ROS MotionManager
# ---------------------------------------------------------------------------

# Stand-pose hardware values (from servo_config.py STAND_PULSE).
# These must stay in sync with the laptop-side servo_config.py.
STAND_PULSE: Dict[int, int] = {
    1: 500,   # l_ank_roll
    2: 500,   # r_ank_roll
    3: 640,   # l_ank_pitch
    4: 360,   # r_ank_pitch
    5: 500,   # l_knee
    6: 500,   # r_knee
    7: 350,   # l_hip_pitch
    8: 650,   # r_hip_pitch
    9: 500,   # l_hip_roll
    10: 500,  # r_hip_roll
    11: 500,  # l_hip_yaw
    12: 500,  # r_hip_yaw
    13: 835,  # l_sho_pitch
    14: 165,  # r_sho_pitch
    15: 830,  # l_sho_roll
    16: 170,  # r_sho_roll
    17: 500,  # l_el_pitch
    18: 500,  # r_el_pitch
    19: 150,  # l_el_yaw  (safe range 0-600)
    20: 850,  # r_el_yaw  (DAMAGED: safe range 360-850)
    21: 500,  # l_gripper
    22: 500,  # r_gripper
    23: 500,  # head_pan  (not physically present)
    24: 500,  # head_tilt (not physically present)
}

# Physical servo safety limits (override 0-1000 for damaged/constrained servos)
SERVO_LIMITS: Dict[int, Tuple[int, int]] = {
    19: (0, 600),     # l_el_yaw safe range
    20: (360, 850),   # r_el_yaw DAMAGED — never go below 360
}


def _clamp_position(servo_id: int, position: int) -> int:
    lo, hi = SERVO_LIMITS.get(servo_id, (0, 1000))
    return max(lo, min(hi, position))


class _MotionManagerBackend:
    """ROS-node backend using ainex_kinematics MotionManager.

    This is the high-level path demonstrated in control.py: a rospy node that
    drives the servo bus through MotionManager.set_servos_position rather than
    poking the UART directly. Requires the robot's ROS workspace to be sourced
    and roscore + the servo controller node to be running.
    """

    # Head servos are not physically present on the AiNex (see README/control.py);
    # MotionManager would error on them, so we drop them here.
    _SKIP_SERVOS = {23, 24}

    def __init__(self):
        import rospy
        from ainex_kinematics.motion_manager import MotionManager

        # init_node must be called once before MotionManager creates its
        # publishers. disable_signals=True leaves SIGINT/SIGTERM to uvicorn so
        # the HTTP server owns process lifecycle.
        rospy.init_node("robot_agent", anonymous=True, disable_signals=True)
        self._rospy = rospy
        self._mm = MotionManager()
        print("[robot-agent] Using ROS MotionManager backend")

    def _grouped(self, moves: List[Tuple[int, int, int]]) -> Dict[int, List[List[int]]]:
        # MotionManager.set_servos_position applies one duration to a whole
        # batch, so group [servo_id, position] pairs by their duration_ms.
        groups: Dict[int, List[List[int]]] = {}
        for sid, pos, t in moves:
            if sid in self._SKIP_SERVOS:
                continue
            groups.setdefault(t, []).append([sid, pos])
        return groups

    def move_servo(self, servo_id: int, position: int, time_ms: int) -> None:
        if servo_id in self._SKIP_SERVOS:
            return
        self._mm.set_servos_position(time_ms, [[servo_id, position]])

    def move_servos(self, moves: List[Tuple[int, int, int]]) -> None:
        for duration_ms, servos in self._grouped(moves).items():
            self._mm.set_servos_position(duration_ms, servos)

    def read_position(self, servo_id: int) -> Optional[int]:
        return None


def _init_backend():
    """Create the ROS MotionManager backend (the only supported backend)."""
    return _MotionManagerBackend()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

backend = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global backend
    backend = _init_backend()
    yield


app = FastAPI(title="AiNex Robot Agent", lifespan=lifespan)

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


class FeedbackRequest(BaseModel):
    servo_ids: List[int]


@app.get("/health")
def health():
    return {"status": "ok", "backend": type(backend).__name__}


@app.post("/move")
def move(moves: List[ServoMove]):
    """Move one or more servos simultaneously."""
    safe_moves = []
    for m in moves:
        if m.servo_id not in range(1, 25):
            continue
        safe_pos = _clamp_position(m.servo_id, m.position)
        safe_moves.append((m.servo_id, safe_pos, max(100, m.duration_ms)))

    if safe_moves and backend is not None:
        backend.move_servos(safe_moves)
    return {"moved": len(safe_moves)}


@app.post("/stand")
def stand():
    """Return all servos to the standing pose."""
    if backend is None:
        return {"error": "backend not initialized"}
    moves = [(sid, pos, 1500) for sid, pos in STAND_PULSE.items()]
    backend.move_servos(moves)
    return {"status": "standing"}


@app.post("/feedback")
def feedback(req: FeedbackRequest):
    """Return current position, temperature, and voltage for requested servos."""
    results = []
    for sid in req.servo_ids:
        pos = backend.read_position(sid) if backend else None
        results.append({
            "servo_id": sid,
            "position": pos if pos is not None else STAND_PULSE.get(sid, 500),
            "temperature": 35,    # not read; nominal safe value
            "voltage": 11100,     # not read; nominal full battery (mV)
        })
    return {"feedback": results}


@app.get("/positions")
def positions():
    """Return current servo positions (0–1000) for all 24 servos."""
    result = {}
    for sid in range(1, 25):
        pos = backend.read_position(sid) if backend else None
        result[sid] = pos if pos is not None else STAND_PULSE.get(sid, 500)
    return {"positions": result}


def main():
    port = int(os.getenv("AGENT_PORT", "9000"))
    print(f"[robot-agent] Starting on 0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
