"""Hardware-specific angle conversion for physical AiNex servos.

The sim uses CENTER_UNITS=500 as neutral for all joints.
Hardware uses per-joint STAND_PULSE as neutral, and some joints have opposite
polarity between the MuJoCo model and physical servo direction.

Conversion formula per joint:
    delta_rad = rad - HW_STAND_RAD[joint]
    hw_units  = STAND_PULSE[joint] + round(delta_rad * TICKS_PER_RAD * HW_DIRECTION[joint])

HW_STAND_RAD captures the MuJoCo ctrl value at the stand keyframe (non-zero for
shoulder-roll and elbow-yaw joints whose stand poses are offset from zero).
HW_DIRECTION is +1 when hardware and sim have the same increasing direction, -1 otherwise.
"""

import math
from .servo_config import STAND_PULSE, TICKS_PER_RAD

# Arm joints whose MuJoCo stand-keyframe ctrl value is not 0.0.
# Derived from the STAND_* constants in primitives.py.
HW_STAND_RAD: dict[str, float] = {
    "l_sho_roll": -1.403,   # STAND_L_SHO_ROLL
    "r_sho_roll":  1.403,   # STAND_R_SHO_ROLL
    "l_el_yaw":   -1.226,   # STAND_L_EL_YAW
    "r_el_yaw":    1.226,   # STAND_R_EL_YAW
}

# +1: hw increases as sim rad increases; -1: hw decreases as sim rad increases.
# Analytically derived for arm joints; leg/head joints are best-effort estimates
# and should be verified during hardware calibration.
HW_DIRECTION: dict[str, int] = {
    # Shoulder pitch — l stands=835 (arm fwd=decrease), r stands=165 (arm fwd=increase)
    "l_sho_pitch": -1,
    "r_sho_pitch": +1,
    # Shoulder roll — both decrease as arm lifts outward (primitives handle sign)
    "l_sho_roll":  -1,
    "r_sho_roll":  -1,
    # Forearm rotation (verified on hardware)
    "l_el_pitch":  -1,   # was +1; confirmed flipped on hardware
    "r_el_pitch":  +1,   # was -1; paired flip with mujoco_sim.py rotate_right_elbow signs
    # Elbow bend — verified on hardware: extend must increase units for l, decrease for r
    "l_el_yaw":    +1,   # was -1; confirmed flipped on hardware (extend was bending)
    "r_el_yaw":    +1,   # was -1; confirmed flipped on hardware (extend was bending)
    # Grippers (verified on hardware)
    "l_gripper":   +1,
    "r_gripper":   +1,   # was -1; confirmed flipped on hardware
    # Head (verified on hardware)
    "head_pan":    -1,   # was +1; confirmed flipped on hardware
    "head_tilt":   +1,
    # Legs — best-effort based on STAND_PULSE polarity; calibrate before use
    "l_ank_roll":  +1,
    "l_ank_pitch": -1,   # stand=640 > 500 → inverted
    "l_knee":      +1,
    "l_hip_pitch": +1,   # stand=350 < 500
    "l_hip_roll":  +1,
    "l_hip_yaw":   +1,
    "r_ank_roll":  -1,
    "r_ank_pitch": +1,   # stand=360 < 500
    "r_knee":      -1,
    "r_hip_pitch": -1,   # stand=650 > 500
    "r_hip_roll":  -1,
    "r_hip_yaw":   -1,
}

# Physical servo limits that override the default 0–1000.
# Servo 20 (r_el_yaw) was mechanically damaged — never command below 360.
HW_SERVO_LIMITS: dict[str, tuple[int, int]] = {
    "l_el_yaw": (0, 600),
    "r_el_yaw": (360, 850),
}

_CENTER = 500
_DEG_PER_UNIT = 240 / 1000


def rad_to_hardware_units(rad: float, joint_name: str) -> int:
    """Convert a simulation radian value to physical servo units for a named joint."""
    stand_pulse = STAND_PULSE.get(joint_name, _CENTER)
    stand_rad   = HW_STAND_RAD.get(joint_name, 0.0)
    direction   = HW_DIRECTION.get(joint_name, +1)

    delta = rad - stand_rad
    units = stand_pulse + round(delta * TICKS_PER_RAD * direction)

    lo, hi = HW_SERVO_LIMITS.get(joint_name, (0, 1000))
    return max(lo, min(hi, units))


def hardware_units_to_rad(hw_units: int, joint_name: str) -> float:
    """Convert physical servo units (0–1000) to simulation radians for a named joint."""
    stand_pulse = STAND_PULSE.get(joint_name, _CENTER)
    stand_rad   = HW_STAND_RAD.get(joint_name, 0.0)
    direction   = HW_DIRECTION.get(joint_name, +1)
    return stand_rad + (hw_units - stand_pulse) * direction / TICKS_PER_RAD


def sim_units_to_hardware_units(sim_units: int, joint_name: str) -> int:
    """Convert pre-computed sim servo units (CENTER=500) to physical servo units.

    The server converts rad→sim_units before building ServoCommands; this function
    reverses that step and applies the hardware-specific mapping.
    """
    degrees = (sim_units - _CENTER) * _DEG_PER_UNIT
    rad = math.radians(degrees)
    return rad_to_hardware_units(rad, joint_name)
