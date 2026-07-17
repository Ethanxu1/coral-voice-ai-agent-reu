"""Motion primitives library for common robot poses.

Each primitive is a function that maps (angle, direction, speed) to joint targets.
The LLM can specify any angle (0-max) and speed (0.1-5.0).
"""

import math
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from validation import JOINT_LIMITS

# Constants
DEFAULT_SPEED = 1.0
DEFAULT_HEAD_SPEED = 5.0  # Head moves faster by default

# Default angles (in degrees)
ARM_DEFAULT_ANGLE = 90
HEAD_TURN_DEFAULT_ANGLE = 45
HEAD_TILT_DEFAULT_ANGLE = 15
ELBOW_DEFAULT_ANGLE = 90

# Angle limits (in degrees)
JOINT_MIN_ANGLE = 0
ARM_OUT_MAX_ANGLE = 119   # ±2.09 rad ≈ 119.7°
ARM_FORWARD_MAX_ANGLE = 119
ELBOW_MAX_ANGLE = 119
HEAD_TURN_MAX_ANGLE = 119
HEAD_TILT_MAX_ANGLE = 119

# Stand-pose arm defaults — must match the `stand` keyframe (ainex.xml) and
# HW_STAND_RAD. Calibrated to the physical robot via tools/author_stand.py.
STAND_L_SHO_ROLL = -1.3614
STAND_R_SHO_ROLL = 1.3614
STAND_L_EL_YAW = -1.5708
STAND_R_EL_YAW = 1.5708


# Helper: degrees to radians
def deg_to_rad(deg: float) -> float:
    return deg * math.pi / 180.0


# Helper: clamp joint value to limits
def clamp_joint(joint_name: str, value: float) -> float:
    limit = JOINT_LIMITS.get(joint_name)
    if limit:
        return limit.clamp(value)
    return value


# --------------------------------------------------------------------------
# Primitive functions
# --------------------------------------------------------------------------


def left_arm_out(
    angle: float = ARM_DEFAULT_ANGLE, speed: float = DEFAULT_SPEED
) -> Tuple[dict, float]:
    """Left arm sideways abduction. angle=0 returns arm to rest at side."""
    rad = deg_to_rad(min(max(angle, JOINT_MIN_ANGLE), ARM_OUT_MAX_ANGLE))
    joints = {
        "l_sho_roll": clamp_joint("l_sho_roll", STAND_L_SHO_ROLL + rad),
    }
    return joints, speed


def right_arm_out(
    angle: float = ARM_DEFAULT_ANGLE, speed: float = DEFAULT_SPEED
) -> Tuple[dict, float]:
    """Right arm sideways abduction. angle=0 returns arm to rest at side."""
    rad = deg_to_rad(min(max(angle, JOINT_MIN_ANGLE), ARM_OUT_MAX_ANGLE))
    joints = {
        "r_sho_roll": clamp_joint("r_sho_roll", STAND_R_SHO_ROLL - rad),
    }
    return joints, speed


def left_arm_forward(
    angle: float = ARM_DEFAULT_ANGLE, speed: float = DEFAULT_SPEED
) -> Tuple[dict, float]:
    """Left arm forward/up flexion. Only moves pitch axis."""
    rad = deg_to_rad(min(max(angle, JOINT_MIN_ANGLE), ARM_FORWARD_MAX_ANGLE))
    joints = {
        "l_sho_pitch": clamp_joint("l_sho_pitch", rad),
    }
    return joints, speed


def right_arm_forward(
    angle: float = ARM_DEFAULT_ANGLE, speed: float = DEFAULT_SPEED
) -> Tuple[dict, float]:
    """Right arm forward/up flexion. Only moves pitch axis."""
    rad = deg_to_rad(min(max(angle, JOINT_MIN_ANGLE), ARM_FORWARD_MAX_ANGLE))
    joints = {
        "r_sho_pitch": clamp_joint("r_sho_pitch", rad),
    }
    return joints, speed


def left_elbow_bend(
    angle: float = ELBOW_DEFAULT_ANGLE, speed: float = DEFAULT_SPEED
) -> Tuple[dict, float]:
    """Bend left elbow (flexion via l_el_yaw)."""
    rad = deg_to_rad(min(max(angle, JOINT_MIN_ANGLE), ELBOW_MAX_ANGLE))
    joints = {"l_el_yaw": clamp_joint("l_el_yaw", -rad)}
    return joints, speed


def right_elbow_bend(
    angle: float = ELBOW_DEFAULT_ANGLE, speed: float = DEFAULT_SPEED
) -> Tuple[dict, float]:
    """Bend right elbow (flexion via r_el_yaw)."""
    rad = deg_to_rad(min(max(angle, JOINT_MIN_ANGLE), ELBOW_MAX_ANGLE))
    joints = {"r_el_yaw": clamp_joint("r_el_yaw", rad)}
    return joints, speed


def left_elbow_rotate(
    angle: float = ELBOW_DEFAULT_ANGLE,
    direction: str = "in",
    speed: float = DEFAULT_SPEED,
) -> Tuple[dict, float]:
    """Rotate left forearm (l_el_pitch). direction='in' or 'out'."""
    rad = deg_to_rad(min(max(angle, JOINT_MIN_ANGLE), ELBOW_MAX_ANGLE))
    sign = -1 if direction == "in" else 1
    joints = {"l_el_pitch": clamp_joint("l_el_pitch", sign * rad)}
    return joints, speed


def right_elbow_rotate(
    angle: float = ELBOW_DEFAULT_ANGLE,
    direction: str = "in",
    speed: float = DEFAULT_SPEED,
) -> Tuple[dict, float]:
    """Rotate right forearm (r_el_pitch). direction='in' or 'out'."""
    rad = deg_to_rad(min(max(angle, JOINT_MIN_ANGLE), ELBOW_MAX_ANGLE))
    sign = 1 if direction == "in" else -1
    joints = {"r_el_pitch": clamp_joint("r_el_pitch", sign * rad)}
    return joints, speed


def head_turn(
    angle: float = HEAD_TURN_DEFAULT_ANGLE,
    direction: str = "left",
    speed: float = DEFAULT_HEAD_SPEED,
) -> Tuple[dict, float]:
    """Turn head left/right. direction='left' or 'right'."""
    rad = deg_to_rad(min(max(angle, JOINT_MIN_ANGLE), HEAD_TURN_MAX_ANGLE))
    sign = -1 if direction == "left" else 1
    joints = {"head_pan": clamp_joint("head_pan", sign * rad)}
    return joints, speed


def head_tilt(
    angle: float = HEAD_TILT_DEFAULT_ANGLE,
    direction: str = "up",
    speed: float = DEFAULT_HEAD_SPEED,
) -> Tuple[dict, float]:
    """Tilt head up/down. direction='up' or 'down'."""
    rad = deg_to_rad(min(max(angle, JOINT_MIN_ANGLE), HEAD_TILT_MAX_ANGLE))
    sign = -1 if direction == "down" else 1
    joints = {"head_tilt": clamp_joint("head_tilt", sign * rad)}
    return joints, speed


def neutral(angle: float = 0, speed: float = DEFAULT_SPEED) -> Tuple[dict, float]:
    """Return all arm and head joints to natural standing position."""
    joints = {
        "l_sho_pitch": 0.0,
        "l_sho_roll": STAND_L_SHO_ROLL,
        "l_el_yaw": STAND_L_EL_YAW,
        "l_el_pitch": 0.0,
        "r_sho_pitch": 0.0,
        "r_sho_roll": STAND_R_SHO_ROLL,
        "r_el_yaw": STAND_R_EL_YAW,
        "r_el_pitch": 0.0,
        "head_pan": 0.0,
        "head_tilt": 0.0,
    }
    return joints, speed


# --------------------------------------------------------------------------
# Registry of primitive functions with metadata
# --------------------------------------------------------------------------


@dataclass
class PrimitiveInfo:
    name: str
    func: Callable
    description: str
    max_angle: float
    bidirectional: bool
    tags: list
    default_angle: float
    default_speed: float = DEFAULT_SPEED


PRIMITIVE_REGISTRY: dict[str, PrimitiveInfo] = {
    "left_arm_out": PrimitiveInfo(
        name="left_arm_out",
        func=left_arm_out,
        description="Left arm sideways (abduction)",
        max_angle=ARM_OUT_MAX_ANGLE,
        bidirectional=False,
        tags=["left", "arm", "out", "side"],
        default_angle=ARM_DEFAULT_ANGLE,
    ),
    "right_arm_out": PrimitiveInfo(
        name="right_arm_out",
        func=right_arm_out,
        description="Right arm sideways (abduction)",
        max_angle=ARM_OUT_MAX_ANGLE,
        bidirectional=False,
        tags=["right", "arm", "out", "side"],
        default_angle=ARM_DEFAULT_ANGLE,
    ),
    "left_arm_forward": PrimitiveInfo(
        name="left_arm_forward",
        func=left_arm_forward,
        description="Left arm forward/up (flexion)",
        max_angle=ARM_FORWARD_MAX_ANGLE,
        bidirectional=False,
        tags=["left", "arm", "forward", "up"],
        default_angle=ARM_DEFAULT_ANGLE,
    ),
    "right_arm_forward": PrimitiveInfo(
        name="right_arm_forward",
        func=right_arm_forward,
        description="Right arm forward/up (flexion)",
        max_angle=ARM_FORWARD_MAX_ANGLE,
        bidirectional=False,
        tags=["right", "arm", "forward", "up"],
        default_angle=ARM_DEFAULT_ANGLE,
    ),
    "left_elbow_bend": PrimitiveInfo(
        name="left_elbow_bend",
        func=left_elbow_bend,
        description="Bend left elbow",
        max_angle=ELBOW_MAX_ANGLE,
        bidirectional=False,
        tags=["left", "elbow", "bend"],
        default_angle=ELBOW_DEFAULT_ANGLE,
    ),
    "right_elbow_bend": PrimitiveInfo(
        name="right_elbow_bend",
        func=right_elbow_bend,
        description="Bend right elbow",
        max_angle=ELBOW_MAX_ANGLE,
        bidirectional=False,
        tags=["right", "elbow", "bend"],
        default_angle=ELBOW_DEFAULT_ANGLE,
    ),
    "left_elbow_rotate": PrimitiveInfo(
        name="left_elbow_rotate",
        func=left_elbow_rotate,
        description="Rotate left forearm in/out",
        max_angle=ELBOW_MAX_ANGLE,
        bidirectional=True,
        tags=["left", "elbow", "rotate", "forearm"],
        default_angle=ELBOW_DEFAULT_ANGLE,
    ),
    "right_elbow_rotate": PrimitiveInfo(
        name="right_elbow_rotate",
        func=right_elbow_rotate,
        description="Rotate right forearm in/out",
        max_angle=ELBOW_MAX_ANGLE,
        bidirectional=True,
        tags=["right", "elbow", "rotate", "forearm"],
        default_angle=ELBOW_DEFAULT_ANGLE,
    ),
    "head_turn": PrimitiveInfo(
        name="head_turn",
        func=head_turn,
        description="Turn head left/right",
        max_angle=HEAD_TURN_MAX_ANGLE,
        bidirectional=True,
        tags=["head", "turn", "yaw"],
        default_angle=HEAD_TURN_DEFAULT_ANGLE,
        default_speed=DEFAULT_HEAD_SPEED,
    ),
    "head_tilt": PrimitiveInfo(
        name="head_tilt",
        func=head_tilt,
        description="Tilt head up/down",
        max_angle=HEAD_TILT_MAX_ANGLE,
        bidirectional=True,
        tags=["head", "tilt", "pitch"],
        default_angle=HEAD_TILT_DEFAULT_ANGLE,
        default_speed=DEFAULT_HEAD_SPEED,
    ),
    "neutral": PrimitiveInfo(
        name="neutral",
        func=neutral,
        description="Reset all joints to zero",
        max_angle=0,
        bidirectional=False,
        tags=["neutral", "reset", "home"],
        default_angle=0,
        default_speed=DEFAULT_SPEED,
    ),
}

# --------------------------------------------------------------------------
# Public API for LLM and server
# --------------------------------------------------------------------------


def resolve_primitive(
    name: str,
    angle: Optional[float] = None,
    direction: Optional[str] = None,
    speed: Optional[float] = None,
) -> Optional[Tuple[dict, float, str]]:
    """Resolve a primitive to joint values.

    Args:
        name: Primitive name
        angle: Angle in degrees (if None, uses primitive's default_angle)
        direction: For bidirectional primitives ('left'/'right'/'up'/'down')
        speed: Speed multiplier (if None, uses primitive's default_speed)

    Returns:
        Tuple of (joints_dict, speed, resolved_name) or None if not found
    """
    name_lower = name.lower()
    info = PRIMITIVE_REGISTRY.get(name_lower)
    if not info:
        return None

    # Use defaults
    if angle is None:
        angle = info.default_angle
    if speed is None:
        speed = info.default_speed

    # Clamp angle
    angle = max(0, min(angle, info.max_angle))

    # Call the primitive function
    if info.bidirectional:
        if direction is None:
            if "elbow_rotate" in name_lower:
                direction = "in"
            elif "turn" in name_lower or "rotate" in name_lower:
                direction = "left"
            else:
                direction = "up"
        joints, final_speed = info.func(angle, direction, speed)
    else:
        joints, final_speed = info.func(angle, speed)

    return joints, final_speed, info.name


def get_primitive(name: str):
    """Legacy API: returns a MotionPrimitive-like object for backward compatibility."""
    result = resolve_primitive(name)
    if not result:
        return None
    joints, speed, resolved_name = result
    info = PRIMITIVE_REGISTRY.get(resolved_name)

    # Create a simple object with the needed attributes
    class LegacyPrimitive:
        def __init__(self, name, joints, speed, description, tags):
            self.name = name
            self.joints = joints
            self.speed = speed
            self.description = description
            self.tags = tags

    return LegacyPrimitive(
        name=resolved_name,
        joints=joints,
        speed=speed,
        description=info.description if info else resolved_name,
        tags=info.tags if info else [],
    )


def get_primitives_list() -> str:
    """Get formatted list of primitives for LLM prompts."""
    lines = ["Available motion primitives (parameterized):", ""]
    lines.append("**Single-side primitives** (specify angle 0-max°):")
    for name, info in PRIMITIVE_REGISTRY.items():
        if info.name == "neutral" or info.bidirectional:
            continue
        lines.append(f"  - `{name}`: {info.description} (max {info.max_angle}°)")
    lines.append("")
    lines.append("**Bidirectional primitives** (specify angle AND direction):")
    for name, info in PRIMITIVE_REGISTRY.items():
        if info.bidirectional:
            if "elbow_rotate" in name:
                dirs = "in/out"
            elif "turn" in name or "rotate" in name:
                dirs = "left/right"
            else:
                dirs = "up/down"
            lines.append(
                f"  - `{name}`: {info.description} (max {info.max_angle}°, direction: {dirs})"
            )
    lines.append("")
    lines.append("**Special:**")
    lines.append("  - `neutral`: Reset all joints to zero")
    return "\n".join(lines)


def get_primitives_metadata() -> list[dict]:
    """Get metadata for all primitives (for API response)."""
    metadata = []
    for name, info in PRIMITIVE_REGISTRY.items():
        metadata.append(
            {
                "name": info.name,
                "description": info.description,
                "type": "parameterized" if not info.bidirectional else "bidirectional",
                "max_angle": info.max_angle,
                "default_angle": info.default_angle,
                "bidirectional": info.bidirectional,
                "default_speed": info.default_speed,
                "tags": info.tags,
            }
        )
    return metadata


# Legacy PRIMITIVES dict (for backward compatibility, built on demand)
def _build_legacy_primitives():
    primitives = {}
    for name in PRIMITIVE_REGISTRY:
        p = get_primitive(name)
        if p:
            primitives[name] = p
    return primitives


PRIMITIVES = _build_legacy_primitives()
PRIMITIVE_NAMES = list(PRIMITIVE_REGISTRY.keys())

# Aliases for natural language matching
PRIMITIVE_ALIASES: dict[str, str] = {
    "left arm out": "left_arm_out",
    "right arm out": "right_arm_out",
    "left arm forward": "left_arm_forward",
    "right arm forward": "right_arm_forward",
    "look left": "head_turn",
    "look right": "head_turn",
    "turn left": "head_turn",
    "turn right": "head_turn",
    "look up": "head_tilt",
    "look down": "head_tilt",
    "reset": "neutral",
    "home": "neutral",
    "rest": "neutral",
}


def get_parameterized_primitive(name: str):
    """Return the PrimitiveInfo for a given name (for compatibility)."""
    return PRIMITIVE_REGISTRY.get(name.lower())


def categorize_primitive(name: str) -> str:
    """Categorize a primitive for UI grouping."""
    name_lower = name.lower()
    if name_lower == "neutral":
        return "rest"
    if "arm" in name_lower and "out" in name_lower:
        return "arms_out"
    if "arm" in name_lower and "forward" in name_lower:
        return "arms_forward"
    if "elbow" in name_lower:
        return "elbow"
    if "head" in name_lower:
        return "head"
    if "torso" in name_lower:
        return "torso"
    return "other"


def detect_degrees_in_request(message: str) -> Optional[str]:
    """Detect degree values in user request and provide radian conversion hints."""
    import re

    pattern = r"(\d+)\s*(?:degrees?|°)"
    matches = re.findall(pattern, message.lower())
    if matches:
        hints = [f"{d}° = {float(d) * 0.01745:.2f} rad" for d in matches[:3]]
        return "DEGREE CONVERSION: " + ", ".join(hints)
    return None


def resolve_primitive_as_commands(
    name: str,
    angle: Optional[float] = None,
    direction: Optional[str] = None,
    speed: Optional[float] = None,
):
    """Resolve a primitive to a list of ServoCommands ready to send to the controller."""
    from robot.interface import ServoCommand
    from robot.servo_config import SERVO_ID_MAP
    from robot.angle_utils import rad_to_servo_units, speed_to_duration_ms

    result = resolve_primitive(name, angle, direction, speed)
    if result is None:
        return None
    joints, final_speed, _ = result
    duration_ms = speed_to_duration_ms(final_speed)
    commands = []
    for joint_name, rad in joints.items():
        servo_id = SERVO_ID_MAP.get(joint_name)
        if servo_id is not None:
            commands.append(ServoCommand(
                servo_id=servo_id,
                position=rad_to_servo_units(rad),
                duration_ms=duration_ms,
            ))
    return commands


