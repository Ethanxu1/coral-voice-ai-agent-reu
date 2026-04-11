"""Motion primitives library for common robot poses.

Each primitive is a function that maps (angle, direction, speed) to joint targets.
The LLM can specify any angle (0-max) and speed (0.1-5.0).
"""

import math
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from coral_agent.validation import JOINT_LIMITS

# Constants
DEFAULT_SPEED = 1.0
DEFAULT_HEAD_SPEED = 2.0  # Head moves faster by default

# Default angles (in degrees)
ARM_DEFAULT_ANGLE = 90
HEAD_TURN_DEFAULT_ANGLE = 45
HEAD_TILT_DEFAULT_ANGLE = 15
TORSO_ROTATE_DEFAULT_ANGLE = 45
TORSO_LEAN_DEFAULT_ANGLE = 17
ELBOW_DEFAULT_ANGLE = 90


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
    """Left arm sideways abduction."""
    rad = deg_to_rad(min(max(angle, 0), 160))
    joints = {
        "l_shoulder_aa": clamp_joint("l_shoulder_aa", rad),
        "l_shoulder_fe": 0.0,
        "l_elbow": 0.0,
    }
    return joints, speed


def right_arm_out(
    angle: float = ARM_DEFAULT_ANGLE, speed: float = DEFAULT_SPEED
) -> Tuple[dict, float]:
    """Right arm sideways abduction."""
    rad = deg_to_rad(min(max(angle, 0), 160))
    joints = {
        "r_shoulder_aa": clamp_joint("r_shoulder_aa", -rad),
        "r_shoulder_fe": 0.0,
        "r_elbow": 0.0,
    }
    return joints, speed


def left_arm_forward(
    angle: float = ARM_DEFAULT_ANGLE, speed: float = DEFAULT_SPEED
) -> Tuple[dict, float]:
    """Left arm forward flexion."""
    rad = deg_to_rad(min(max(angle, 0), 125))
    joints = {
        "l_shoulder_fe": clamp_joint("l_shoulder_fe", -rad),
        "l_shoulder_aa": 0.0,
        "l_elbow": 0.0,
    }
    return joints, speed


def right_arm_forward(
    angle: float = ARM_DEFAULT_ANGLE, speed: float = DEFAULT_SPEED
) -> Tuple[dict, float]:
    """Right arm forward flexion."""
    rad = deg_to_rad(min(max(angle, 0), 125))
    joints = {
        "r_shoulder_fe": clamp_joint("r_shoulder_fe", -rad),
        "r_shoulder_aa": 0.0,
        "r_elbow": 0.0,
    }
    return joints, speed


def left_elbow_bend(
    angle: float = ELBOW_DEFAULT_ANGLE, speed: float = DEFAULT_SPEED
) -> Tuple[dict, float]:
    """Bend left elbow."""
    rad = deg_to_rad(min(max(angle, 0), 150))
    joints = {"l_elbow": clamp_joint("l_elbow", -rad)}
    return joints, speed


def right_elbow_bend(
    angle: float = ELBOW_DEFAULT_ANGLE, speed: float = DEFAULT_SPEED
) -> Tuple[dict, float]:
    """Bend right elbow."""
    rad = deg_to_rad(min(max(angle, 0), 150))
    joints = {"r_elbow": clamp_joint("r_elbow", -rad)}
    return joints, speed


def head_turn(
    angle: float = HEAD_TURN_DEFAULT_ANGLE,
    direction: str = "left",
    speed: float = DEFAULT_HEAD_SPEED,
) -> Tuple[dict, float]:
    """Turn head left/right. direction='left' or 'right'."""
    rad = deg_to_rad(min(max(angle, 0), 95))
    sign = 1 if direction == "left" else -1
    joints = {"neck_yaw": clamp_joint("neck_yaw", sign * rad), "neck_pitch": 0.0}
    return joints, speed


def head_tilt(
    angle: float = HEAD_TILT_DEFAULT_ANGLE,
    direction: str = "up",
    speed: float = DEFAULT_HEAD_SPEED,
) -> Tuple[dict, float]:
    """Tilt head up/down. direction='up' or 'down'."""
    rad = deg_to_rad(min(max(angle, 0), 30))
    # Positive = down, negative = up
    sign = 1 if direction == "down" else -1
    joints = {"neck_pitch": clamp_joint("neck_pitch", sign * rad), "neck_yaw": 0.0}
    return joints, speed


def torso_rotate(
    angle: float = TORSO_ROTATE_DEFAULT_ANGLE,
    direction: str = "left",
    speed: float = DEFAULT_SPEED,
) -> Tuple[dict, float]:
    """Rotate torso left/right."""
    rad = deg_to_rad(min(max(angle, 0), 47))
    sign = 1 if direction == "left" else -1
    joints = {"torso_yaw": clamp_joint("torso_yaw", sign * rad), "torso_pitch": 0.0}
    return joints, speed


def torso_lean(
    angle: float = TORSO_LEAN_DEFAULT_ANGLE, speed: float = DEFAULT_SPEED
) -> Tuple[dict, float]:
    """Lean torso forward."""
    rad = deg_to_rad(min(max(angle, 0), 77))
    joints = {"torso_pitch": clamp_joint("torso_pitch", rad), "torso_yaw": 0.0}
    return joints, speed


# Composite primitives (use same angle for both sides)
def arms_out(
    angle: float = ARM_DEFAULT_ANGLE, speed: float = DEFAULT_SPEED
) -> Tuple[dict, float]:
    """Both arms sideways."""
    left_joints, _ = left_arm_out(angle, speed)
    right_joints, _ = right_arm_out(angle, speed)
    joints = {**left_joints, **right_joints}
    return joints, speed


def arms_forward(
    angle: float = ARM_DEFAULT_ANGLE, speed: float = DEFAULT_SPEED
) -> Tuple[dict, float]:
    """Both arms forward."""
    left_joints, _ = left_arm_forward(angle, speed)
    right_joints, _ = right_arm_forward(angle, speed)
    joints = {**left_joints, **right_joints}
    return joints, speed


def elbows_bend(
    angle: float = ELBOW_DEFAULT_ANGLE, speed: float = DEFAULT_SPEED
) -> Tuple[dict, float]:
    """Bend both elbows."""
    left_joints, _ = left_elbow_bend(angle, speed)
    right_joints, _ = right_elbow_bend(angle, speed)
    joints = {**left_joints, **right_joints}
    return joints, speed


def neutral(
    angle: float = 0, speed: float = DEFAULT_SPEED
) -> Tuple[dict, float]:
    """Reset all joints to zero (angle parameter ignored for consistency)."""
    joints = {
        "l_shoulder_fe": 0.0,
        "l_shoulder_aa": 0.0,
        "l_elbow": 0.0,
        "r_shoulder_fe": 0.0,
        "r_shoulder_aa": 0.0,
        "r_elbow": 0.0,
        "neck_yaw": 0.0,
        "neck_pitch": 0.0,
        "torso_yaw": 0.0,
        "torso_pitch": 0.0,
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
        max_angle=160,
        bidirectional=False,
        tags=["left", "arm", "out", "side"],
        default_angle=ARM_DEFAULT_ANGLE,
    ),
    "right_arm_out": PrimitiveInfo(
        name="right_arm_out",
        func=right_arm_out,
        description="Right arm sideways (abduction)",
        max_angle=160,
        bidirectional=False,
        tags=["right", "arm", "out", "side"],
        default_angle=ARM_DEFAULT_ANGLE,
    ),
    "left_arm_forward": PrimitiveInfo(
        name="left_arm_forward",
        func=left_arm_forward,
        description="Left arm forward/up (flexion)",
        max_angle=125,
        bidirectional=False,
        tags=["left", "arm", "forward", "up"],
        default_angle=ARM_DEFAULT_ANGLE,
    ),
    "right_arm_forward": PrimitiveInfo(
        name="right_arm_forward",
        func=right_arm_forward,
        description="Right arm forward/up (flexion)",
        max_angle=125,
        bidirectional=False,
        tags=["right", "arm", "forward", "up"],
        default_angle=ARM_DEFAULT_ANGLE,
    ),
    "left_elbow_bend": PrimitiveInfo(
        name="left_elbow_bend",
        func=left_elbow_bend,
        description="Bend left elbow",
        max_angle=150,
        bidirectional=False,
        tags=["left", "elbow", "bend"],
        default_angle=ELBOW_DEFAULT_ANGLE,
    ),
    "right_elbow_bend": PrimitiveInfo(
        name="right_elbow_bend",
        func=right_elbow_bend,
        description="Bend right elbow",
        max_angle=150,
        bidirectional=False,
        tags=["right", "elbow", "bend"],
        default_angle=ELBOW_DEFAULT_ANGLE,
    ),
    "head_turn": PrimitiveInfo(
        name="head_turn",
        func=head_turn,
        description="Turn head left/right",
        max_angle=95,
        bidirectional=True,
        tags=["head", "turn", "yaw"],
        default_angle=HEAD_TURN_DEFAULT_ANGLE,
        default_speed=DEFAULT_HEAD_SPEED,
    ),
    "head_tilt": PrimitiveInfo(
        name="head_tilt",
        func=head_tilt,
        description="Tilt head up/down",
        max_angle=30,
        bidirectional=True,
        tags=["head", "tilt", "pitch"],
        default_angle=HEAD_TILT_DEFAULT_ANGLE,
        default_speed=DEFAULT_HEAD_SPEED,
    ),
    "torso_rotate": PrimitiveInfo(
        name="torso_rotate",
        func=torso_rotate,
        description="Rotate torso left/right",
        max_angle=47,
        bidirectional=True,
        tags=["torso", "rotate", "twist"],
        default_angle=TORSO_ROTATE_DEFAULT_ANGLE,
    ),
    "torso_lean": PrimitiveInfo(
        name="torso_lean",
        func=torso_lean,
        description="Lean torso forward",
        max_angle=77,
        bidirectional=False,
        tags=["torso", "lean", "bow"],
        default_angle=TORSO_LEAN_DEFAULT_ANGLE,
    ),
    "arms_out": PrimitiveInfo(
        name="arms_out",
        func=arms_out,
        description="Both arms sideways (T-pose)",
        max_angle=160,
        bidirectional=False,
        tags=["arms", "both", "out", "tpose"],
        default_angle=ARM_DEFAULT_ANGLE,
    ),
    "arms_forward": PrimitiveInfo(
        name="arms_forward",
        func=arms_forward,
        description="Both arms forward",
        max_angle=125,
        bidirectional=False,
        tags=["arms", "both", "forward"],
        default_angle=ARM_DEFAULT_ANGLE,
    ),
    "elbows_bend": PrimitiveInfo(
        name="elbows_bend",
        func=elbows_bend,
        description="Bend both elbows",
        max_angle=150,
        bidirectional=False,
        tags=["elbows", "both", "bend"],
        default_angle=ELBOW_DEFAULT_ANGLE,
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
            # Default direction for bidirectional primitives
            if "turn" in name_lower or "rotate" in name_lower:
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
    lines.append("**Single-side primitives** (specify angle 0-180°):")
    for name, info in PRIMITIVE_REGISTRY.items():
        if info.name == "neutral":
            continue
        if not info.bidirectional and "arms" not in name and "elbows" not in name:
            lines.append(f"  - `{name}`: {info.description} (max {info.max_angle}°)")
    lines.append("")
    lines.append("**Bidirectional primitives** (specify angle AND direction):")
    for name, info in PRIMITIVE_REGISTRY.items():
        if info.bidirectional:
            dirs = "left/right" if "turn" in name or "rotate" in name else "up/down"
            lines.append(
                f"  - `{name}`: {info.description} (max {info.max_angle}°, direction: {dirs})"
            )
    lines.append("")
    lines.append("**Composite primitives** (both sides):")
    for name in ["arms_out", "arms_forward", "elbows_bend"]:
        info = PRIMITIVE_REGISTRY.get(name)
        if info:
            lines.append(f"  - `{name}`: {info.description}")
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
    "t pose": "arms_out",
    "t-pose": "arms_out",
    "tpose": "arms_out",
    "arms out": "arms_out",
    "arms sideways": "arms_out",
    "left arm out": "left_arm_out",
    "right arm out": "right_arm_out",
    "arms forward": "arms_forward",
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


def detect_plural_arms(message: str) -> Optional[str]:
    """Detect when user is requesting motion for BOTH arms."""
    import re

    patterns = [
        r"\barms\b",
        r"\bboth\s+arm",
        r"\bleft\s+and\s+right",
        r"\bright\s+and\s+left",
    ]
    for pattern in patterns:
        if re.search(pattern, message.lower()):
            return "PLURAL ARMS DETECTED: Use composite primitives like 'arms_out' or 'arms_forward'."
    return None
