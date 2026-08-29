import math

# Hiwonder servo: 1000 units = 240 degrees
_UNITS_PER_DEGREE = 1000 / 240   # ≈ 4.167
_DEGREES_PER_UNIT = 240 / 1000   # = 0.24°

# Used as the neutral offset in sim mode (MuJoCo rad=0 ↔ servo 500).
# Phase 2 MUST replace this with per-joint STAND_PULSE values from servo_config.py,
# because most physical joints have asymmetric stand positions (e.g. l_sho_pitch=835).
CENTER_UNITS = 500


def rad_to_servo_units(rad: float) -> int:
    """Convert radians (signed, 0 = sim neutral) to Hiwonder servo units (0–1000).

    Assumes CENTER_UNITS=500 as neutral — valid for sim only.
    Phase 2 hardware controller must apply per-joint STAND_PULSE offsets.
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
