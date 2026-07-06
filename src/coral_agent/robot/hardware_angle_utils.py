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
    # Legs — derived by cross-checking motions.py's STAND_LOW_PULSE crouch
    # (hardware ground truth: l_hip_pitch 350→245, r 650→755, l_knee 500→650,
    # r 500→350, l_ank_pitch 640→720, r 360→280) against the sim's mirrored
    # joint axes in ainex.xml (same physical crouch = opposite-sign radians on
    # the two sides). Mirrored pulses + mirrored axes cancel, so l/r pairs get
    # EQUAL directions — the previous best-effort right-side values were
    # systematically flipped. hip_roll/hip_yaw come from the user-tested pulse
    # sweep (servo 9: 400=outward, servo 10: 600=outward, servo 11:
    # 300=outward, servo 12: 700=outward). Verify on hardware before driving.
    "l_ank_roll":  +1,   # no calibration data — unverified guess
    "l_ank_pitch": -1,   # crouch: dorsiflexion (−rad) → pulse up
    "l_knee":      +1,   # crouch: flexion (+rad) → pulse up
    "l_hip_pitch": +1,   # crouch: flexion (−rad) → pulse down
    "l_hip_roll":  +1,   # sweep: abduction (−rad) → 400 (down)
    "l_hip_yaw":   +1,   # sweep: external rotation (−rad) → 300 (down)
    "r_ank_roll":  -1,   # no calibration data — unverified guess
    "r_ank_pitch": -1,   # was +1; crouch: dorsiflexion (+rad) → pulse down
    "r_knee":      +1,   # was -1; crouch: flexion (−rad) → pulse down
    "r_hip_pitch": +1,   # was -1; crouch: flexion (+rad) → pulse up
    "r_hip_roll":  +1,   # was -1; sweep: abduction (+rad) → 600 (up)
    "r_hip_yaw":   +1,   # was -1; sweep: external rotation (+rad) → 700 (up)
}

# Physical servo limits that override the default 0–1000. Measured per-servo
# safe ranges for all 8 arm servos (13-20); servo 20 (r_el_yaw) was mechanically
# damaged — never command below 360, reflected in its range below.
# Leg servos: hip_roll (9/10) and hip_yaw (11/12) are user-tested sweeps;
# hip_pitch (5-8) and knee ranges are NOT hardware-swept — they're conservative
# bounds derived from the retargeting angle caps around each stand pulse.
HW_SERVO_LIMITS: dict[str, tuple[int, int]] = {
    "l_sho_pitch": (333, 835),   # servo 13
    "r_sho_pitch": (200, 773),   # servo 14
    "l_sho_roll":  (440, 800),   # servo 15
    "r_sho_roll":  (213, 613),   # servo 16
    "l_el_pitch":  (440, 653),   # servo 17
    "r_el_pitch":  (320, 560),   # servo 18
    "l_el_yaw":    (90, 360),    # servo 19
    "r_el_yaw":    (573, 880),   # servo 20
    "l_knee":      (440, 760),   # servo 5  — conservative, stand=500
    "r_knee":      (240, 560),   # servo 6  — conservative, stand=500
    "l_hip_pitch": (150, 450),   # servo 7  — conservative, stand=350
    "r_hip_pitch": (550, 850),   # servo 8  — conservative, stand=650
    "l_hip_roll":  (400, 600),   # servo 9  — user-tested: 400=outward 30°, 600=inward 20°
    "r_hip_roll":  (400, 600),   # servo 10 — user-tested: 400=inward 20°, 600=outward 30°
    "l_hip_yaw":   (300, 600),   # servo 11 — user-tested: 300=outward 45°, 600=inward 20°
    "r_hip_yaw":   (400, 700),   # servo 12 — user-tested: 400=inward 20°, 700=outward 45°
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
