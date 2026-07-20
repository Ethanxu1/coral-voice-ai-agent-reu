"""Servo ID map, stand-pose pulse values, and unit conversions for the AiNex 24-DOF robot.

SERVO_ID_MAP  — joint name → hardware servo ID (1–24)
STAND_PULSE   — hardware neutral pulse for each joint (not 500 for all; arms/ankles are asymmetric)
TICKS_PER_RAD — unit conversion constant for all HX-series servos
"""

# Servo IDs verified against ak-maker/ainex_skeleton_following (tested on hardware).
# Left/right legs interleave: left=odd IDs, right=even IDs (1-12).
# Arms follow: left=13,15,17,19,21  right=14,16,18,20,22.
# Head (23, 24) are defined in firmware but NOT physically present on the robot.
SERVO_ID_MAP: dict[str, int] = {
    # Left leg (odd IDs 1-11)
    "l_ank_roll":  1,
    "l_ank_pitch": 3,
    "l_knee":      5,
    "l_hip_pitch": 7,
    "l_hip_roll":  9,
    "l_hip_yaw":   11,
    # Right leg (even IDs 2-12)
    "r_ank_roll":  2,
    "r_ank_pitch": 4,
    "r_knee":      6,
    "r_hip_pitch": 8,
    "r_hip_roll":  10,
    "r_hip_yaw":   12,
    # Left arm (odd IDs 13-21)
    "l_sho_pitch": 13,
    "l_sho_roll":  15,
    "l_el_pitch":  17,   # physically: forearm rotation (YAML name is misleading)
    "l_el_yaw":    19,   # physically: elbow bend (YAML name is misleading)
    "l_gripper":   21,
    # Right arm (even IDs 14-22)
    "r_sho_pitch": 14,
    "r_sho_roll":  16,
    "r_el_pitch":  18,   # physically: forearm rotation
    "r_el_yaw":    20,   # physically: elbow bend (servo 20 has limited range 360-850)
    "r_gripper":   22,
    # Head — NOT physically present on hardware; firmware IDs reserved
    "head_pan":    23,
    "head_tilt":   24,
}

# Reverse map: servo ID → joint name
JOINT_NAME_MAP: dict[int, str] = {v: k for k, v in SERVO_ID_MAP.items()}

# Standing-pose pulse values confirmed from hardware (stand.d6a action file).
# These are the hardware neutral positions — NOT 500 for all joints.
# Phase 2 angle conversion must use these as per-joint offsets rather than the
# universal CENTER_UNITS=500 used in sim mode.
STAND_PULSE: dict[str, int] = {
    "l_ank_roll":  500,
    "l_ank_pitch": 640,
    "l_knee":      500,
    "l_hip_pitch": 350,
    "l_hip_roll":  500,
    "l_hip_yaw":   500,
    "r_ank_roll":  500,
    "r_ank_pitch": 360,
    "r_knee":      500,
    "r_hip_pitch": 650,
    "r_hip_roll":  500,
    "r_hip_yaw":   500,
    "l_sho_pitch": 835,
    "l_sho_roll":  830,
    "l_el_pitch":  500,
    "l_el_yaw":    150,
    "l_gripper":   500,
    "r_sho_pitch": 165,
    "r_sho_roll":  170,
    "r_el_pitch":  500,
    "r_el_yaw":    850,
    "r_gripper":   500,
    "head_pan":    500,
    "head_tilt":   500,
}

# Encoder ticks per radian — same for all HX-series servos.
# Derived from: 1000 units / 240° * (180°/π) ≈ 238.73 ticks/rad
TICKS_PER_RAD: float = 1000 / 240 * (180 / 3.141592653589793)
