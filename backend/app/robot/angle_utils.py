"""Sim-side angle/servo-unit conversions (uniform 500-centre map).

Hardware-calibrated conversions (per-joint stand pulses, mirror-mounted
servos) live in hardware_angle_utils.py and are applied only inside
hardware_controller.py.
"""

import math

from app.robot.interface import ServoCommand
from app.robot.servo_config import SERVO_ID_MAP

# Hiwonder servo: 1000 units = 240 degrees
_UNITS_PER_DEGREE = 1000 / 240   # ≈ 4.167
_DEGREES_PER_UNIT = 240 / 1000   # = 0.24°

# Neutral offset of the sim map (MuJoCo rad=0 ↔ servo 500).
CENTER_UNITS = 500


def rad_to_servo_units(rad: float) -> int:
    """Convert radians (signed, 0 = sim neutral) to Hiwonder servo units (0–1000).

    Assumes CENTER_UNITS=500 as neutral; the hardware controller re-maps these
    to each joint's real stand pulse.
    """
    degrees = math.degrees(rad)
    units = CENTER_UNITS + round(degrees * _UNITS_PER_DEGREE)
    return max(0, min(1000, units))


def servo_units_to_rad(units: int) -> float:
    """Convert Hiwonder servo units (0–1000) to signed radians (0 = sim neutral)."""
    degrees = (units - CENTER_UNITS) * _DEGREES_PER_UNIT
    return math.radians(degrees)


def speed_to_duration_ms(speed: float) -> int:
    """Convert abstract speed multiplier (0.1–8.0) to move duration in milliseconds.

    speed=1.0 → 1000ms  speed=5.0 → 200ms  speed=0.1 → 5000ms (clamped)
    """
    return max(200, min(5000, round(1000 / speed)))


def joints_to_servo_commands(joints: dict[str, float], duration_ms: int) -> list[ServoCommand]:
    """Convert {joint name: radians} to sim-unit ServoCommands, skipping unknown joints."""
    return [
        ServoCommand(
            servo_id=SERVO_ID_MAP[joint],
            position=rad_to_servo_units(rad),
            duration_ms=duration_ms,
        )
        for joint, rad in joints.items()
        if joint in SERVO_ID_MAP
    ]
