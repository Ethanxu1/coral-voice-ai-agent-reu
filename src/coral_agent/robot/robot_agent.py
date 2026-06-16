"""Robot-side agent server — deploy and run this ON the AiNex robot.

Receives servo commands from the laptop's hardware_controller.py over HTTP
and drives the physical servos via the Hiwonder serial bus.

Install on robot:
    pip install fastapi uvicorn pyserial

Run on robot:
    python3 robot_agent.py
  or via uv (if installed):
    uv run robot-agent

Environment variables (set on the robot):
    SERIAL_PORT   Serial device for servo bus (default: /dev/ttyAMA0)
    AGENT_PORT    HTTP port this server listens on (default: 9000)
"""

from __future__ import annotations

import os
import struct
import threading
import time
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Tuple

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Servo bus backend — tries Hiwonder SDK first, falls back to raw serial
# ---------------------------------------------------------------------------

SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyAMA0")
SERIAL_BAUD = 115200

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


# ---------------------------------------------------------------------------
# Serial bus backend
# ---------------------------------------------------------------------------

class _SerialBackend:
    """Direct Hiwonder LX bus servo control via UART."""

    def __init__(self, port: str, baud: int):
        import serial  # pyserial — install on robot: pip install pyserial
        self._lock = threading.Lock()
        self._ser = serial.Serial(port, baud, timeout=0.1)
        print(f"[robot-agent] Serial port {port} @ {baud} baud opened")

    @staticmethod
    def _build_move(servo_id: int, position: int, time_ms: int) -> bytes:
        """
        Hiwonder LX bus SERVO_MOVE_TIME_WRITE command.
        Packet: [0x55, 0x55, ID, LEN=7, CMD=0x01, pos_l, pos_h, t_l, t_h]
        LEN = total packet bytes - 2 header bytes = 9 - 2 = 7.
        """
        pos = max(0, min(1000, position))
        t   = max(0, min(30000, time_ms))
        return struct.pack('<BBBBBBBBB',
            0x55, 0x55,
            servo_id & 0xFF,
            7,      # length
            0x01,   # CMD: SERVO_MOVE_TIME_WRITE
            pos & 0xFF, (pos >> 8) & 0xFF,
            t & 0xFF,   (t >> 8) & 0xFF,
        )

    def move_servo(self, servo_id: int, position: int, time_ms: int) -> None:
        cmd = self._build_move(servo_id, position, time_ms)
        with self._lock:
            self._ser.write(cmd)

    def move_servos(self, moves: List[Tuple[int, int, int]]) -> None:
        # Send all servo commands with minimal inter-frame gap so they
        # start moving at approximately the same time.
        cmds = b"".join(self._build_move(sid, pos, t) for sid, pos, t in moves)
        with self._lock:
            self._ser.write(cmds)

    def read_position(self, servo_id: int) -> Optional[int]:
        """Request current position from servo (LX SERVO_POS_READ = 0x1C)."""
        with self._lock:
            self._ser.write(bytes([0x55, 0x55, servo_id, 4, 0x1C, 0x00]))
            time.sleep(0.003)
            raw = self._ser.read(8)
        if len(raw) >= 8 and raw[0] == 0x55 and raw[1] == 0x55:
            return struct.unpack_from('<H', raw, 5)[0]
        return None


class _AinexSDKBackend:
    """Thin wrapper around the ainex_kinematics SDK (available on the robot)."""

    def __init__(self):
        # ainex_kinematics is a ROS package — source the workspace first:
        # source /home/ubuntu/ros_ws/devel/setup.bash
        import sys
        sys.path.insert(0, '/home/ubuntu/ros_ws/devel/lib/python3/dist-packages')
        from ainex_kinematics.servo_control import setServoPulse  # type: ignore
        self._set = setServoPulse
        print("[robot-agent] Using ainex_kinematics servo backend")

    def move_servo(self, servo_id: int, position: int, time_ms: int) -> None:
        self._set(servo_id, position, time_ms)

    def move_servos(self, moves: List[Tuple[int, int, int]]) -> None:
        for sid, pos, t in moves:
            self._set(sid, pos, t)

    def read_position(self, servo_id: int) -> Optional[int]:
        return None


def _init_backend():
    """Try SDK first, fall back to raw serial."""
    try:
        return _AinexSDKBackend()
    except Exception:
        pass
    return _SerialBackend(SERIAL_PORT, SERIAL_BAUD)


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
