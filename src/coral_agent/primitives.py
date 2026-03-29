"""Motion primitives library for common robot poses.

These are tested, validated poses that eliminate the need for the LLM to guess raw angles.
Using primitives significantly improves consistency over raw angle regression.
"""

import re
from dataclasses import dataclass


@dataclass
class MotionPrimitive:
    """A named motion primitive with joint targets and metadata."""

    name: str
    description: str
    joints: dict[str, float]
    tags: list[str]  # For semantic matching


# Core motion primitives library
# All joint values have been validated against MuJoCo model limits
PRIMITIVES: dict[str, MotionPrimitive] = {
    # === NEUTRAL/REST POSES ===
    "neutral": MotionPrimitive(
        name="neutral",
        description="Neutral standing position with arms at sides",
        joints={
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
        },
        tags=["rest", "default", "reset", "home", "neutral", "relax"],
    ),
    "arms_down": MotionPrimitive(
        name="arms_down",
        description="Both arms relaxed at sides",
        joints={
            "l_shoulder_fe": 0.1,
            "l_shoulder_aa": 0.0,
            "l_elbow": -0.1,
            "r_shoulder_fe": 0.1,
            "r_shoulder_aa": 0.0,
            "r_elbow": -0.1,
        },
        tags=["rest", "relax", "down", "lower"],
    ),
    # === T-POSE / ARMS OUT ===
    "t_pose": MotionPrimitive(
        name="t_pose",
        description="Both arms extended horizontally (T-pose)",
        joints={
            "l_shoulder_fe": -1.5,
            "l_shoulder_aa": 1.5,  # Positive for left arm outward
            "l_elbow": 0.0,
            "r_shoulder_fe": -1.5,
            "r_shoulder_aa": -1.5,  # Negative for right arm outward
            "r_elbow": 0.0,
        },
        tags=["t-pose", "tpose", "arms out", "horizontal", "spread"],
    ),
    "left_arm_out": MotionPrimitive(
        name="left_arm_out",
        description="Left arm extended horizontally to the side",
        joints={
            "l_shoulder_fe": -1.5,
            "l_shoulder_aa": 1.5,
            "l_elbow": 0.0,
        },
        tags=["left", "arm out", "side", "horizontal"],
    ),
    "right_arm_out": MotionPrimitive(
        name="right_arm_out",
        description="Right arm extended horizontally to the side",
        joints={
            "r_shoulder_fe": -1.5,
            "r_shoulder_aa": -1.5,
            "r_elbow": 0.0,
        },
        tags=["right", "arm out", "side", "horizontal"],
    ),
    # === POINTING ===
    "point_forward": MotionPrimitive(
        name="point_forward",
        description="Right arm pointing forward",
        joints={
            "r_shoulder_fe": -0.8,
            "r_shoulder_aa": 0.0,
            "r_elbow": 0.0,
        },
        tags=["point", "forward", "right", "indicate"],
    ),
    "point_forward_left": MotionPrimitive(
        name="point_forward_left",
        description="Left arm pointing forward",
        joints={
            "l_shoulder_fe": -0.8,
            "l_shoulder_aa": 0.0,
            "l_elbow": 0.0,
        },
        tags=["point", "forward", "left", "indicate"],
    ),
    # === WAVING ===
    "wave_right": MotionPrimitive(
        name="wave_right",
        description="Right arm raised in waving position",
        joints={
            "r_shoulder_fe": -1.2,
            "r_shoulder_aa": -0.5,
            "r_elbow": -1.2,
        },
        tags=["wave", "hello", "hi", "greeting", "right"],
    ),
    "wave_left": MotionPrimitive(
        name="wave_left",
        description="Left arm raised in waving position",
        joints={
            "l_shoulder_fe": -1.2,
            "l_shoulder_aa": 0.5,
            "l_elbow": -1.2,
        },
        tags=["wave", "hello", "hi", "greeting", "left"],
    ),
    # === HEAD MOVEMENTS ===
    "look_left": MotionPrimitive(
        name="look_left",
        description="Head turned left",
        joints={
            "neck_yaw": 0.5,
        },
        tags=["look", "left", "head", "turn"],
    ),
    "look_right": MotionPrimitive(
        name="look_right",
        description="Head turned right",
        joints={
            "neck_yaw": -0.5,
        },
        tags=["look", "right", "head", "turn"],
    ),
    "look_up": MotionPrimitive(
        name="look_up",
        description="Head tilted up",
        joints={
            "neck_pitch": -0.2,
        },
        tags=["look", "up", "head", "tilt"],
    ),
    "look_down": MotionPrimitive(
        name="look_down",
        description="Head tilted down",
        joints={
            "neck_pitch": 0.4,
        },
        tags=["look", "down", "head", "tilt"],
    ),
    "nod_yes": MotionPrimitive(
        name="nod_yes",
        description="Head nodding down (yes gesture)",
        joints={
            "neck_pitch": 0.3,
        },
        tags=["nod", "yes", "agree", "affirm"],
    ),
    "shake_no": MotionPrimitive(
        name="shake_no",
        description="Head turned to side (no gesture)",
        joints={
            "neck_yaw": -0.4,
        },
        tags=["shake", "no", "disagree", "deny"],
    ),
    # === ARMS UP ===
    "arms_up": MotionPrimitive(
        name="arms_up",
        description="Both arms raised above head",
        joints={
            "l_shoulder_fe": -2.0,
            "l_shoulder_aa": 0.3,
            "l_elbow": 0.0,
            "r_shoulder_fe": -2.0,
            "r_shoulder_aa": -0.3,
            "r_elbow": 0.0,
        },
        tags=["arms up", "raise", "celebration", "surrender", "stretch"],
    ),
    "arms_up_and_out": MotionPrimitive(
        name="arms_up_and_out",
        description="Both arms raised up AND extended outward to sides (diagonal up-out)",
        joints={
            "l_shoulder_fe": -1.57,  # Arms forward/up
            "l_shoulder_aa": 1.2,    # POSITIVE for left arm OUT
            "l_elbow": 0.0,
            "r_shoulder_fe": -1.57,  # Arms forward/up
            "r_shoulder_aa": -1.2,   # NEGATIVE for right arm OUT
            "r_elbow": 0.0,
        },
        tags=["arms up", "arms out", "up and out", "diagonal", "spread", "both"],
    ),
    "right_arm_up": MotionPrimitive(
        name="right_arm_up",
        description="Right arm raised above head",
        joints={
            "r_shoulder_fe": -2.0,
            "r_shoulder_aa": -0.3,
            "r_elbow": 0.0,
        },
        tags=["right", "arm up", "raise"],
    ),
    "left_arm_up": MotionPrimitive(
        name="left_arm_up",
        description="Left arm raised above head",
        joints={
            "l_shoulder_fe": -2.0,
            "l_shoulder_aa": 0.3,
            "l_elbow": 0.0,
        },
        tags=["left", "arm up", "raise"],
    ),
    # === EXPRESSIVE POSES ===
    "thinking": MotionPrimitive(
        name="thinking",
        description="Hand near chin in thinking pose",
        joints={
            "r_shoulder_fe": -0.3,
            "r_shoulder_aa": 0.1,
            "r_elbow": -2.0,
            "neck_pitch": 0.1,
        },
        tags=["think", "thinking", "ponder", "consider"],
    ),
    "shrug": MotionPrimitive(
        name="shrug",
        description="Both shoulders slightly raised (shrug gesture)",
        joints={
            "l_shoulder_fe": -0.4,
            "l_shoulder_aa": 0.4,
            "l_elbow": -0.8,
            "r_shoulder_fe": -0.4,
            "r_shoulder_aa": -0.4,
            "r_elbow": -0.8,
        },
        tags=["shrug", "dunno", "unsure", "uncertain"],
    ),
    # === SINGLE ARM 90-DEGREE OUTWARD ===
    "right_arm_90_out": MotionPrimitive(
        name="right_arm_90_out",
        description="Right arm extended 90 degrees outward (sideways)",
        joints={
            "r_shoulder_fe": -1.5,
            "r_shoulder_aa": -1.5,
            "r_elbow": 0.0,
        },
        tags=["right", "90", "outward", "sideways", "degrees"],
    ),
    "left_arm_90_out": MotionPrimitive(
        name="left_arm_90_out",
        description="Left arm extended 90 degrees outward (sideways)",
        joints={
            "l_shoulder_fe": -1.5,
            "l_shoulder_aa": 1.5,
            "l_elbow": 0.0,
        },
        tags=["left", "90", "outward", "sideways", "degrees"],
    ),
    # === 45-DEGREE ARM POSITIONS ===
    "right_arm_45_out": MotionPrimitive(
        name="right_arm_45_out",
        description="Right arm extended 45 degrees outward",
        joints={
            "r_shoulder_fe": -0.79,
            "r_shoulder_aa": -0.79,  # NEGATIVE for right arm out
            "r_elbow": 0.0,
        },
        tags=["right", "45", "outward", "degrees"],
    ),
    "left_arm_45_out": MotionPrimitive(
        name="left_arm_45_out",
        description="Left arm extended 45 degrees outward",
        joints={
            "l_shoulder_fe": -0.79,
            "l_shoulder_aa": 0.79,  # POSITIVE for left arm out
            "l_elbow": 0.0,
        },
        tags=["left", "45", "outward", "degrees"],
    ),
    "both_arms_45_out": MotionPrimitive(
        name="both_arms_45_out",
        description="Both arms extended 45 degrees outward",
        joints={
            "l_shoulder_fe": -0.79,
            "l_shoulder_aa": 0.79,  # POSITIVE for left arm out
            "l_elbow": 0.0,
            "r_shoulder_fe": -0.79,
            "r_shoulder_aa": -0.79,  # NEGATIVE for right arm out
            "r_elbow": 0.0,
        },
        tags=["both", "arms", "45", "outward", "degrees"],
    ),
    # === HEAD FULL TURNS ===
    "look_far_left": MotionPrimitive(
        name="look_far_left",
        description="Head turned all the way left",
        joints={
            "neck_yaw": 1.65,  # POSITIVE = LEFT
        },
        tags=["look", "far", "left", "all the way", "maximum"],
    ),
    "look_far_right": MotionPrimitive(
        name="look_far_right",
        description="Head turned all the way right",
        joints={
            "neck_yaw": -1.65,  # NEGATIVE = RIGHT
        },
        tags=["look", "far", "right", "all the way", "maximum"],
    ),
}


# Aliases for common LLM mistakes / alternative phrasings
PRIMITIVE_ALIASES: dict[str, str] = {
    # Arms down variations
    "left arm down": "arms_down",
    "right arm down": "arms_down",
    "both arms down": "arms_down",
    "lower arms": "arms_down",
    "put arms down": "arms_down",
    "l_arm_down": "arms_down",
    "r_arm_down": "arms_down",
    # T-pose variations (90 degrees)
    "both arms out": "t_pose",
    "both left and right arm out": "t_pose",
    "arms out": "t_pose",
    "spread arms": "t_pose",
    "arms outward": "t_pose",
    "arms to the side": "t_pose",
    # Arms up and out variations
    "arms up and out": "arms_up_and_out",
    "both arms up and out": "arms_up_and_out",
    "arms up out": "arms_up_and_out",
    "arms out and up": "arms_up_and_out",
    "both_arms_up_out": "arms_up_and_out",
    "arms up and out to the side": "arms_up_and_out",
    # 45-degree variations
    "arms 45 out": "both_arms_45_out",
    "arms 45 degrees": "both_arms_45_out",
    "both arms 45": "both_arms_45_out",
    "arms outward 45": "both_arms_45_out",
    "arms out 45 degrees": "both_arms_45_out",
    "arms outwards 45 degrees": "both_arms_45_out",
    "arms outwards by 45 degrees": "both_arms_45_out",
    "left arm 45 out": "left_arm_45_out",
    "left arm 45 degrees": "left_arm_45_out",
    "right arm 45 out": "right_arm_45_out",
    "right arm 45 degrees": "right_arm_45_out",
    # Wave variations
    "wave": "wave_right",
    "wave hello": "wave_right",
    "wave right hand": "wave_right",
    "wave left hand": "wave_left",
    # Look variations
    "turn head left": "look_left",
    "turn head right": "look_right",
    "look left": "look_left",
    "look right": "look_right",
    "head all the way left": "look_far_left",
    "head all the way right": "look_far_right",
    "look all the way left": "look_far_left",
    "look all the way right": "look_far_right",
    # Point variations
    "point": "point_forward",
    "point forward right": "point_forward",
    "point forward left": "point_forward_left",
}


def get_primitive(name: str) -> MotionPrimitive | None:
    """Get a motion primitive by name.

    Args:
        name: Name of the primitive (case-insensitive)

    Returns:
        MotionPrimitive if found, None otherwise
    """
    normalized = name.lower().replace("-", "_").replace(" ", "_")

    # Direct lookup first
    if normalized in PRIMITIVES:
        return PRIMITIVES[normalized]

    # Try alias lookup (with original spacing for phrase matching)
    name_lower = name.lower().strip()
    if name_lower in PRIMITIVE_ALIASES:
        return PRIMITIVES.get(PRIMITIVE_ALIASES[name_lower])

    # Try fuzzy matching - find best match
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
        Formatted string describing available primitives
    """
    lines = ["Available motion primitives:"]
    for name, prim in PRIMITIVES.items():
        lines.append(f"  - {name}: {prim.description}")
    return "\n".join(lines)


# Quick lookup for the system prompt
PRIMITIVE_NAMES = list(PRIMITIVES.keys())


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
                "Use l_shoulder_aa POSITIVE for left arm out, r_shoulder_aa NEGATIVE for right arm out. "
                "Consider using 'both_arms_45_out' or 't_pose' primitive if applicable."
            )

    return None
