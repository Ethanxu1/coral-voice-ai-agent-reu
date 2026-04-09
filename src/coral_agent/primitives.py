"""Motion primitives library for common robot poses.

These are tested, validated poses that eliminate the need for the LLM to guess raw angles.
Using primitives significantly improves consistency over raw angle regression.

Joint naming convention (Apollo robot):
- l/r_shoulder_fe: Flexion/Extension - moves arm forward/back (negative = forward/up)
- l/r_shoulder_aa: Abduction/Adduction - moves arm sideways (left: positive = out, right: negative = out)
- l/r_elbow: Elbow bend (negative = bent)
- neck_yaw: Head turn (positive = left, negative = right)
- neck_pitch: Head tilt (positive = down, negative = up)
- torso_yaw: Torso rotation (positive = left, negative = right)
- torso_pitch: Torso lean (positive = forward)

IMPORTANT: Each primitive sets ALL joints for the affected body part to ensure
clean poses regardless of previous state.
"""

import math
import re
from dataclasses import dataclass, field


@dataclass
class MotionPrimitive:
    """A named motion primitive with joint targets and metadata (legacy)."""

    name: str
    description: str
    joints: dict[str, float]
    tags: list[str]
    speed: float = 1.0  # Default speed multiplier


@dataclass
class ParameterizedPrimitive:
    """A parameterized motion primitive that accepts angle and speed inputs.

    This replaces the old system of having separate primitives for each angle
    (e.g., arms_out_45, arms_out_90) with a single primitive that accepts
    the angle as a parameter.
    """

    name: str
    description: str
    joint_name: str  # Primary joint to control
    sign: int  # +1 or -1 to apply to the angle
    default_angle: float  # Default angle in degrees
    max_angle: float  # Maximum angle in degrees
    related_joints: dict[str, float] = field(default_factory=dict)  # Joints to reset
    tags: list[str] = field(default_factory=list)
    default_speed: float = 1.0
    bidirectional: bool = False  # Needs direction parameter (left/right, up/down)

    def compute_joints(
        self,
        angle: float | None = None,
        direction: str | None = None,
        speed: float | None = None,
    ) -> tuple[dict[str, float], float]:
        """Compute joint values for the given angle and direction.

        Args:
            angle: Angle in degrees (uses default_angle if None)
            direction: Direction for bidirectional primitives (left/right, up/down)
            speed: Speed multiplier (uses default_speed if None)

        Returns:
            Tuple of (joint_values dict, speed)
        """
        # Use defaults if not provided
        if angle is None:
            angle = self.default_angle
        if speed is None:
            speed = self.default_speed

        # Clamp angle to valid range
        angle = max(0, min(angle, self.max_angle))

        # Convert degrees to radians
        radians = angle * math.pi / 180.0

        # Determine sign based on direction for bidirectional primitives
        effective_sign = self.sign
        if self.bidirectional and direction:
            direction_lower = direction.lower()
            # For head/torso rotation: left is positive, right is negative
            if direction_lower in ("right", "down"):
                effective_sign = -1
            elif direction_lower in ("left", "up"):
                effective_sign = 1

        # Build joint values
        joints = self.related_joints.copy()
        joints[self.joint_name] = effective_sign * radians

        return joints, speed


# Speed constants
HEAD_SPEED = 3.0  # Head movements are 3x faster
DEFAULT_SPEED = 1.0


# Parameterized primitives - the new system with ~11 base primitives
PARAMETERIZED_PRIMITIVES: dict[str, ParameterizedPrimitive] = {
    # === ARM PRIMITIVES ===
    "left_arm_out": ParameterizedPrimitive(
        name="left_arm_out",
        description="Left arm sideways (abduction)",
        joint_name="l_shoulder_aa",
        sign=1,  # Positive = left arm out
        default_angle=90,
        max_angle=160,  # Limited by joint range ~1.6 rad = 92°
        related_joints={"l_shoulder_fe": 0.0, "l_elbow": 0.0},
        tags=["left", "arm", "out", "side", "abduction"],
        default_speed=DEFAULT_SPEED,
    ),
    "right_arm_out": ParameterizedPrimitive(
        name="right_arm_out",
        description="Right arm sideways (abduction)",
        joint_name="r_shoulder_aa",
        sign=-1,  # Negative = right arm out
        default_angle=90,
        max_angle=160,  # Limited by joint range ~1.6 rad = 92°
        related_joints={"r_shoulder_fe": 0.0, "r_elbow": 0.0},
        tags=["right", "arm", "out", "side", "abduction"],
        default_speed=DEFAULT_SPEED,
    ),
    "left_arm_forward": ParameterizedPrimitive(
        name="left_arm_forward",
        description="Left arm forward (flexion)",
        joint_name="l_shoulder_fe",
        sign=-1,  # Negative = forward
        default_angle=90,
        max_angle=125,  # Limited by joint range ~2.18 rad = 125°
        related_joints={"l_shoulder_aa": 0.0, "l_elbow": 0.0},
        tags=["left", "arm", "forward", "front", "flexion"],
        default_speed=DEFAULT_SPEED,
    ),
    "right_arm_forward": ParameterizedPrimitive(
        name="right_arm_forward",
        description="Right arm forward (flexion)",
        joint_name="r_shoulder_fe",
        sign=-1,  # Negative = forward
        default_angle=90,
        max_angle=125,  # Limited by joint range ~2.18 rad = 125°
        related_joints={"r_shoulder_aa": 0.0, "r_elbow": 0.0},
        tags=["right", "arm", "forward", "front", "flexion"],
        default_speed=DEFAULT_SPEED,
    ),
    "left_elbow_bend": ParameterizedPrimitive(
        name="left_elbow_bend",
        description="Bend left elbow",
        joint_name="l_elbow",
        sign=-1,  # Negative = bent
        default_angle=90,
        max_angle=150,  # Limited by joint range ~2.62 rad = 150°
        related_joints={},  # Elbow-only, don't reset shoulder
        tags=["left", "elbow", "bend", "bent"],
        default_speed=DEFAULT_SPEED,
    ),
    "right_elbow_bend": ParameterizedPrimitive(
        name="right_elbow_bend",
        description="Bend right elbow",
        joint_name="r_elbow",
        sign=-1,  # Negative = bent
        default_angle=90,
        max_angle=150,  # Limited by joint range ~2.62 rad = 150°
        related_joints={},  # Elbow-only, don't reset shoulder
        tags=["right", "elbow", "bend", "bent"],
        default_speed=DEFAULT_SPEED,
    ),
    # === HEAD PRIMITIVES ===
    "head_turn": ParameterizedPrimitive(
        name="head_turn",
        description="Turn head left or right",
        joint_name="neck_yaw",
        sign=1,  # Base sign (will be modified by direction)
        default_angle=45,
        max_angle=95,  # Limited by joint range ~1.66 rad = 95°
        related_joints={"neck_pitch": 0.0},
        tags=["head", "turn", "look", "yaw"],
        default_speed=HEAD_SPEED,
        bidirectional=True,  # Needs direction: left/right
    ),
    "head_tilt": ParameterizedPrimitive(
        name="head_tilt",
        description="Tilt head up or down",
        joint_name="neck_pitch",
        sign=1,  # Base sign (will be modified by direction)
        default_angle=15,
        max_angle=30,  # Limited by joint range: up=-0.26rad(15°), down=0.52rad(30°)
        related_joints={"neck_yaw": 0.0},
        tags=["head", "tilt", "nod", "pitch"],
        default_speed=HEAD_SPEED,
        bidirectional=True,  # Needs direction: up/down
    ),
    # === TORSO PRIMITIVES ===
    "torso_rotate": ParameterizedPrimitive(
        name="torso_rotate",
        description="Rotate torso left or right",
        joint_name="torso_yaw",
        sign=1,  # Base sign (will be modified by direction)
        default_angle=45,
        max_angle=47,  # Limited by joint range ~0.83 rad = 47°
        related_joints={"torso_pitch": 0.0},
        tags=["torso", "rotate", "turn", "twist"],
        default_speed=DEFAULT_SPEED,
        bidirectional=True,  # Needs direction: left/right
    ),
    "torso_lean": ParameterizedPrimitive(
        name="torso_lean",
        description="Lean torso forward",
        joint_name="torso_pitch",
        sign=1,  # Positive = forward lean
        default_angle=17,
        max_angle=77,  # Limited by joint range ~1.35 rad = 77°
        related_joints={"torso_yaw": 0.0},
        tags=["torso", "lean", "bow", "forward"],
        default_speed=DEFAULT_SPEED,
    ),
}


# Composite primitives that combine left and right
@dataclass
class CompositePrimitive:
    """A composite primitive that combines multiple parameterized primitives."""

    name: str
    description: str
    components: list[str]  # Names of ParameterizedPrimitive to combine
    tags: list[str]
    default_speed: float = 1.0

    def compute_joints(
        self,
        angle: float | None = None,
        direction: str | None = None,
        speed: float | None = None,
    ) -> tuple[dict[str, float], float]:
        """Compute combined joint values from all components."""
        combined_joints: dict[str, float] = {}
        final_speed = speed if speed is not None else self.default_speed

        for comp_name in self.components:
            prim = PARAMETERIZED_PRIMITIVES.get(comp_name)
            if prim:
                joints, _ = prim.compute_joints(angle, direction, speed)
                combined_joints.update(joints)

        return combined_joints, final_speed


COMPOSITE_PRIMITIVES: dict[str, CompositePrimitive] = {
    "arms_out": CompositePrimitive(
        name="arms_out",
        description="Both arms sideways (T-pose at 90°)",
        components=["left_arm_out", "right_arm_out"],
        tags=["arms", "both", "out", "side", "abduction", "t-pose", "tpose"],
        default_speed=DEFAULT_SPEED,
    ),
    "arms_forward": CompositePrimitive(
        name="arms_forward",
        description="Both arms forward",
        components=["left_arm_forward", "right_arm_forward"],
        tags=["arms", "both", "forward", "front", "flexion"],
        default_speed=DEFAULT_SPEED,
    ),
    "elbows_bend": CompositePrimitive(
        name="elbows_bend",
        description="Bend both elbows",
        components=["left_elbow_bend", "right_elbow_bend"],
        tags=["elbows", "both", "bend", "bent"],
        default_speed=DEFAULT_SPEED,
    ),
}


# Neutral primitive (special case - resets all joints)
NEUTRAL_JOINTS = {
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


# Backward compatibility aliases: old name -> (new_name, angle, direction)
# This maps the old hardcoded primitive names to the new parameterized system
PARAMETERIZED_ALIASES: dict[str, tuple[str, float, str | None]] = {
    # Arms out variations
    "arms_out_45": ("arms_out", 45, None),
    "arms_out_90": ("arms_out", 90, None),
    "left_arm_out_45": ("left_arm_out", 45, None),
    "left_arm_out_90": ("left_arm_out", 90, None),
    "right_arm_out_45": ("right_arm_out", 45, None),
    "right_arm_out_90": ("right_arm_out", 90, None),
    # Arms forward variations
    "arms_forward_45": ("arms_forward", 45, None),
    "arms_forward_90": ("arms_forward", 90, None),
    "left_arm_forward_45": ("left_arm_forward", 45, None),
    "left_arm_forward_90": ("left_arm_forward", 90, None),
    "right_arm_forward_45": ("right_arm_forward", 45, None),
    "right_arm_forward_90": ("right_arm_forward", 90, None),
    # Elbow variations
    "left_elbow_bent_45": ("left_elbow_bend", 45, None),
    "left_elbow_bent_90": ("left_elbow_bend", 90, None),
    "right_elbow_bent_45": ("right_elbow_bend", 45, None),
    "right_elbow_bent_90": ("right_elbow_bend", 90, None),
    # Head variations
    "head_left_45": ("head_turn", 45, "left"),
    "head_left_90": ("head_turn", 90, "left"),
    "head_right_45": ("head_turn", 45, "right"),
    "head_right_90": ("head_turn", 90, "right"),
    "head_up": ("head_tilt", 15, "up"),
    "head_down": ("head_tilt", 23, "down"),  # ~0.4 rad
    "head_center": ("head_turn", 0, None),
    # Torso variations
    "torso_left_45": ("torso_rotate", 45, "left"),
    "torso_right_45": ("torso_rotate", 45, "right"),
    "torso_forward": ("torso_lean", 17, None),  # ~0.3 rad
    "torso_center": ("torso_rotate", 0, None),
}


# Simple string aliases (for typos, common phrasings)
PRIMITIVE_ALIASES: dict[str, str] = {
    # Neutral variations
    "reset": "neutral",
    "home": "neutral",
    "rest": "neutral",
    "default": "neutral",
    "zero": "neutral",
    # T-pose
    "t pose": "arms_out",
    "t-pose": "arms_out",
    "tpose": "arms_out",
    # Arms out variations
    "arms out": "arms_out",
    "arms to the side": "arms_out",
    "arms sideways": "arms_out",
    "left arm out": "left_arm_out",
    "right arm out": "right_arm_out",
    # Arms forward variations
    "arms forward": "arms_forward",
    "arms straight forward": "arms_forward",
    "left arm forward": "left_arm_forward",
    "right arm forward": "right_arm_forward",
    # Head variations
    "look left": "head_turn",
    "turn left": "head_turn",
    "look right": "head_turn",
    "turn right": "head_turn",
    "look up": "head_tilt",
    "look down": "head_tilt",
    "look straight": "neutral",
    "look forward": "neutral",
}


def get_parameterized_primitive(
    name: str,
) -> ParameterizedPrimitive | CompositePrimitive | None:
    """Get a parameterized primitive by name.

    Args:
        name: Name of the primitive (case-insensitive)

    Returns:
        ParameterizedPrimitive or CompositePrimitive if found, None otherwise
    """
    normalized = name.lower().replace("-", "_").replace(" ", "_")

    # Direct lookup in parameterized primitives
    if normalized in PARAMETERIZED_PRIMITIVES:
        return PARAMETERIZED_PRIMITIVES[normalized]

    # Check composite primitives
    if normalized in COMPOSITE_PRIMITIVES:
        return COMPOSITE_PRIMITIVES[normalized]

    return None


def resolve_primitive(
    name: str,
    angle: float | None = None,
    direction: str | None = None,
    speed: float | None = None,
) -> tuple[dict[str, float], float, str] | None:
    """Resolve a primitive name (with optional parameters) to joint values.

    Handles:
    1. New parameterized primitives (left_arm_out with angle=75)
    2. Old hardcoded names via aliases (arms_out_45 -> arms_out, angle=45)
    3. Neutral as a special case

    Args:
        name: Primitive name
        angle: Angle in degrees (optional)
        direction: Direction for bidirectional primitives (optional)
        speed: Speed multiplier (optional)

    Returns:
        Tuple of (joints dict, speed, resolved_name) or None if not found
    """
    normalized = name.lower().replace("-", "_").replace(" ", "_")

    # Handle neutral specially
    if normalized == "neutral":
        return NEUTRAL_JOINTS.copy(), speed or DEFAULT_SPEED, "neutral"

    # Check for backward-compatibility alias (old names like arms_out_45)
    if normalized in PARAMETERIZED_ALIASES:
        alias_name, alias_angle, alias_direction = PARAMETERIZED_ALIASES[normalized]
        # Use alias values as defaults, but allow overrides
        if angle is None:
            angle = alias_angle
        if direction is None:
            direction = alias_direction
        normalized = alias_name

    # Check simple string aliases
    name_lower = name.lower().strip()
    if name_lower in PRIMITIVE_ALIASES:
        alias_target = PRIMITIVE_ALIASES[name_lower]
        if alias_target == "neutral":
            return NEUTRAL_JOINTS.copy(), speed or DEFAULT_SPEED, "neutral"
        normalized = alias_target

    # Look up the primitive
    prim = get_parameterized_primitive(normalized)
    if prim:
        joints, final_speed = prim.compute_joints(angle, direction, speed)
        return joints, final_speed, prim.name

    return None


# Legacy MotionPrimitive for backward compatibility with existing code
# These are generated from the parameterized system
def _build_legacy_primitives() -> dict[str, MotionPrimitive]:
    """Build legacy PRIMITIVES dict from parameterized system for backward compat."""
    primitives: dict[str, MotionPrimitive] = {}

    # Neutral
    primitives["neutral"] = MotionPrimitive(
        name="neutral",
        description="Neutral standing position with all joints at zero",
        joints=NEUTRAL_JOINTS.copy(),
        tags=["neutral", "rest", "default", "reset", "home", "relax", "zero"],
        speed=DEFAULT_SPEED,
    )

    # Generate legacy primitives from aliases
    for old_name, (new_name, angle, direction) in PARAMETERIZED_ALIASES.items():
        result = resolve_primitive(new_name, angle, direction)
        if result:
            joints, speed, resolved_name = result
            # Get description from the parameterized primitive
            prim = get_parameterized_primitive(new_name)
            if prim:
                desc = f"{prim.description} at {angle}°"
                if direction:
                    desc = f"{prim.description} {direction} at {angle}°"
                primitives[old_name] = MotionPrimitive(
                    name=old_name,
                    description=desc,
                    joints=joints,
                    tags=prim.tags.copy(),
                    speed=speed,
                )

    return primitives


# Build legacy primitives dict
PRIMITIVES: dict[str, MotionPrimitive] = _build_legacy_primitives()


def get_primitive(name: str) -> MotionPrimitive | None:
    """Get a motion primitive by name (legacy API).

    Args:
        name: Name of the primitive (case-insensitive)

    Returns:
        MotionPrimitive if found, None otherwise
    """
    normalized = name.lower().replace("-", "_").replace(" ", "_")

    # Direct lookup first in legacy primitives
    if normalized in PRIMITIVES:
        return PRIMITIVES[normalized]

    # Try alias lookup (with original spacing for phrase matching)
    name_lower = name.lower().strip()
    if name_lower in PRIMITIVE_ALIASES:
        alias_target = PRIMITIVE_ALIASES[name_lower]
        if alias_target in PRIMITIVES:
            return PRIMITIVES[alias_target]
        # May point to a parameterized primitive
        result = resolve_primitive(alias_target)
        if result:
            joints, speed, resolved_name = result
            prim = get_parameterized_primitive(alias_target)
            return MotionPrimitive(
                name=resolved_name,
                description=prim.description if prim else alias_target,
                joints=joints,
                tags=prim.tags if prim else [],
                speed=speed,
            )

    # Try resolving as a parameterized primitive directly
    result = resolve_primitive(name)
    if result:
        joints, speed, resolved_name = result
        prim = get_parameterized_primitive(resolved_name)
        return MotionPrimitive(
            name=resolved_name,
            description=prim.description if prim else resolved_name,
            joints=joints,
            tags=prim.tags if prim else [],
            speed=speed,
        )

    # Try fuzzy matching on legacy primitives
    best_match = None
    best_score = 0

    for prim_name, prim in PRIMITIVES.items():
        # Check if primitive name is contained in input or vice versa
        if prim_name in normalized or normalized in prim_name:
            score = len(prim_name)
            if score > best_score:
                best_score = score
                best_match = prim

        # Check tags
        for tag in prim.tags:
            if tag in name_lower:
                score = len(tag)
                if score > best_score:
                    best_score = score
                    best_match = prim

    return best_match


def find_primitive_by_tags(tags: list[str]) -> list[MotionPrimitive]:
    """Find primitives that match any of the given tags.

    Args:
        tags: List of tags to search for

    Returns:
        List of matching primitives, sorted by number of matching tags
    """
    matches = []
    search_tags = {t.lower() for t in tags}

    for primitive in PRIMITIVES.values():
        primitive_tags = {t.lower() for t in primitive.tags}
        overlap = len(search_tags & primitive_tags)
        if overlap > 0:
            matches.append((overlap, primitive))

    # Sort by number of matching tags (descending)
    matches.sort(key=lambda x: x[0], reverse=True)
    return [m[1] for m in matches]


def get_primitives_list() -> str:
    """Get a formatted list of available primitives for the LLM prompt.

    Returns:
        Formatted string describing available parameterized primitives
    """
    lines = ["Available motion primitives (parameterized):"]
    lines.append("")

    # Parameterized primitives with angle support
    lines.append("SINGLE-SIDE PRIMITIVES (specify angle 0-180°):")
    for name, prim in PARAMETERIZED_PRIMITIVES.items():
        if not prim.bidirectional:
            lines.append(f"  - {name}: {prim.description} (max {prim.max_angle}°)")

    lines.append("")
    lines.append("BIDIRECTIONAL PRIMITIVES (specify angle AND direction):")
    for name, prim in PARAMETERIZED_PRIMITIVES.items():
        if prim.bidirectional:
            if "head" in name:
                dirs = "left/right" if "turn" in name else "up/down"
            else:
                dirs = "left/right"
            lines.append(f"  - {name}: {prim.description} (max {prim.max_angle}°, direction: {dirs})")

    lines.append("")
    lines.append("COMPOSITE PRIMITIVES (both sides at once):")
    for name, prim in COMPOSITE_PRIMITIVES.items():
        lines.append(f"  - {name}: {prim.description}")

    lines.append("")
    lines.append("SPECIAL:")
    lines.append("  - neutral: Reset all joints to zero")

    return "\n".join(lines)


def get_primitives_metadata() -> list[dict]:
    """Get metadata for all primitives (for API response)."""
    metadata = []

    # Add parameterized primitives
    for name, prim in PARAMETERIZED_PRIMITIVES.items():
        metadata.append({
            "name": name,
            "description": prim.description,
            "type": "parameterized",
            "default_angle": prim.default_angle,
            "max_angle": prim.max_angle,
            "bidirectional": prim.bidirectional,
            "default_speed": prim.default_speed,
            "tags": prim.tags,
        })

    # Add composite primitives
    for name, prim in COMPOSITE_PRIMITIVES.items():
        # Get max angle from first component
        first_comp = PARAMETERIZED_PRIMITIVES.get(prim.components[0])
        max_angle = first_comp.max_angle if first_comp else 90
        default_angle = first_comp.default_angle if first_comp else 90

        metadata.append({
            "name": name,
            "description": prim.description,
            "type": "composite",
            "default_angle": default_angle,
            "max_angle": max_angle,
            "bidirectional": False,
            "default_speed": prim.default_speed,
            "tags": prim.tags,
            "components": prim.components,
        })

    # Add neutral
    metadata.append({
        "name": "neutral",
        "description": "Neutral standing position with all joints at zero",
        "type": "special",
        "default_angle": 0,
        "max_angle": 0,
        "bidirectional": False,
        "default_speed": DEFAULT_SPEED,
        "tags": ["neutral", "rest", "default", "reset", "home"],
    })

    return metadata


# Quick lookup for the system prompt
PRIMITIVE_NAMES = list(PRIMITIVES.keys())


def categorize_primitive(name: str) -> str:
    """Categorize a primitive by its name for UI grouping.

    Args:
        name: The primitive name

    Returns:
        Category string for UI display
    """
    name_lower = name.lower()

    if name_lower == "neutral":
        return "rest"

    if "arm" in name_lower and "out" in name_lower:
        return "arms_out"

    if "arm" in name_lower and "forward" in name_lower:
        return "arms_forward"

    if "elbow" in name_lower:
        return "elbow"

    if "head" in name_lower or "neck" in name_lower:
        return "head"

    if "torso" in name_lower:
        return "torso"

    return "other"


# Degree to radian conversion table
DEGREE_TO_RADIAN: dict[str, str] = {
    "15": "0.26",
    "30": "0.52",
    "45": "0.79",
    "60": "1.05",
    "90": "1.57",
    "120": "2.09",
    "180": "3.14",
}


def detect_degrees_in_request(message: str) -> str | None:
    """Detect degree values in user request and provide radian conversion hints.

    Args:
        message: The user's motion request

    Returns:
        Hint string with degree-to-radian conversions, or None if no degrees found
    """
    pattern = r"(\d+)\s*(?:degrees?|°)"
    matches = re.findall(pattern, message.lower())

    if matches:
        hints = []
        for degree in matches:
            if degree in DEGREE_TO_RADIAN:
                hints.append(f"{degree}° = {DEGREE_TO_RADIAN[degree]} rad")
            else:
                # Calculate for non-standard angles
                try:
                    radians = int(degree) * 3.14159 / 180
                    hints.append(f"{degree}° ≈ {radians:.2f} rad")
                except ValueError:
                    pass

        if hints:
            return "DEGREE CONVERSION: " + ", ".join(hints)

    return None


def detect_plural_arms(message: str) -> str | None:
    """Detect when user is requesting motion for BOTH arms.

    Args:
        message: The user's motion request

    Returns:
        Hint string for plural arms handling, or None if single arm
    """
    patterns = [
        r"\barms\b",  # plural "arms"
        r"\bboth\s+arm",  # "both arm(s)"
        r"\bleft\s+and\s+right",  # "left and right"
        r"\bright\s+and\s+left",  # "right and left"
    ]

    for pattern in patterns:
        if re.search(pattern, message.lower()):
            return (
                "PLURAL ARMS DETECTED: You MUST include BOTH left AND right joints. "
                "Use l_shoulder_aa POSITIVE for left arm out, r_shoulder_aa NEGATIVE for right arm out."
            )

    return None
