"""Joint limit validation for waypoints.

Validates waypoints before execution, auto-clamping out-of-range values with warnings.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from coral_agent.simulator import ApolloSimulator


@dataclass
class JointLimit:
    """Joint limit bounds."""

    min: float
    max: float

    def clamp(self, value: float) -> float:
        """Clamp value to within limits."""
        return max(self.min, min(self.max, value))

    def is_valid(self, value: float) -> bool:
        """Check if value is within limits."""
        return self.min <= value <= self.max


# Joint limits extracted from MuJoCo model (apptronik_apollo.xml)
# These are the ctrlrange values from the actuator definitions
JOINT_LIMITS: dict[str, JointLimit] = {
    # Torso
    "torso_yaw": JointLimit(-0.829031, 0.829031),
    "torso_roll": JointLimit(-0.20944, 0.20944),
    "torso_pitch": JointLimit(-0.305433, 1.35263),
    # Neck/Head
    "neck_yaw": JointLimit(-1.65806, 1.65806),
    "neck_roll": JointLimit(-0.785398, 0.785398),
    "neck_pitch": JointLimit(-0.261799, 0.523599),
    # Left arm
    "l_shoulder_aa": JointLimit(-0.122173, 1.6057),
    "l_shoulder_ie": JointLimit(-0.471239, 0.471239),
    "l_shoulder_fe": JointLimit(-2.18166, 0.610865),
    "l_elbow": JointLimit(-2.61799, 0.174533),  # Mapped from l_elbow_fe
    "l_wrist_roll": JointLimit(-1.65806, 1.65806),
    "l_wrist_yaw": JointLimit(-0.785398, 0.785398),
    "l_wrist_pitch": JointLimit(-0.837758, 1.67552),
    # Right arm
    "r_shoulder_aa": JointLimit(-1.6057, 0.122173),
    "r_shoulder_ie": JointLimit(-0.471239, 0.471239),
    "r_shoulder_fe": JointLimit(-2.18166, 0.610865),
    "r_elbow": JointLimit(-2.61799, 0.174533),  # Mapped from r_elbow_fe
    "r_wrist_roll": JointLimit(-1.65806, 1.65806),
    "r_wrist_yaw": JointLimit(-0.785398, 0.785398),
    "r_wrist_pitch": JointLimit(-1.67552, 0.837758),
    # Left leg
    "l_hip_ie": JointLimit(-0.567232, 1.09083),
    "l_hip_aa": JointLimit(-0.218166, 0.741765),
    "l_hip_fe": JointLimit(-1.85005, 0.476475),
    "l_knee": JointLimit(0, 2.61799),  # Mapped from l_knee_fe
    "l_ankle_ie": JointLimit(-0.654498, 0.305433),
    "l_ankle_pd": JointLimit(-1.5708, 0.436332),
    # Right leg
    "r_hip_ie": JointLimit(-1.09083, 0.567232),
    "r_hip_aa": JointLimit(-0.741765, 0.218166),
    "r_hip_fe": JointLimit(-1.85005, 0.476475),
    "r_knee": JointLimit(0, 2.61799),  # Mapped from r_knee_fe
    "r_ankle_ie": JointLimit(-0.305433, 0.654498),
    "r_ankle_pd": JointLimit(-1.5708, 0.436332),
}


@dataclass
class ValidationResult:
    """Result of waypoint validation."""

    original_joints: dict[str, float]
    validated_joints: dict[str, float]
    violations: list[str]
    unknown_joints: list[str]

    @property
    def had_violations(self) -> bool:
        """Check if any violations occurred."""
        return len(self.violations) > 0 or len(self.unknown_joints) > 0


def validate_waypoint(joints: dict[str, float], clamp: bool = True) -> ValidationResult:
    """Validate and optionally clamp joint values.

    Args:
        joints: Dictionary of joint names to target values
        clamp: If True, clamp out-of-range values; if False, reject them

    Returns:
        ValidationResult with validated joints and any violations
    """
    validated = {}
    violations = []
    unknown_joints = []

    for joint_name, value in joints.items():
        limit = JOINT_LIMITS.get(joint_name)

        if limit is None:
            unknown_joints.append(joint_name)
            logger.warning(f"Unknown joint '{joint_name}' - skipping validation")
            validated[joint_name] = value
            continue

        if not limit.is_valid(value):
            clamped = limit.clamp(value)
            violation_msg = (
                f"{joint_name}: {value:.3f} outside [{limit.min:.3f}, {limit.max:.3f}] "
                f"-> clamped to {clamped:.3f}"
            )
            violations.append(violation_msg)
            logger.warning(f"Joint limit violation: {violation_msg}")

            if clamp:
                validated[joint_name] = clamped
            else:
                # Skip invalid joint
                continue
        else:
            validated[joint_name] = value

    return ValidationResult(
        original_joints=joints,
        validated_joints=validated,
        violations=violations,
        unknown_joints=unknown_joints,
    )


def get_joint_limits_from_model(simulator: "ApolloSimulator") -> dict[str, JointLimit]:
    """Extract joint limits directly from the loaded MuJoCo model.

    This can be used to verify or update the static JOINT_LIMITS dictionary.
    """
    import mujoco

    limits = {}
    model = simulator.model

    for i in range(model.nu):  # nu = number of actuators
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, i)
        if name:
            ctrlrange = model.actuator_ctrlrange[i]
            limits[name] = JointLimit(float(ctrlrange[0]), float(ctrlrange[1]))

    return limits


def validate_motion_sign(motion_description: str, joints: dict[str, float]) -> list[str]:
    """Check if joint signs match the described motion.

    This catches common LLM mistakes where signs are confused between left/right.

    Args:
        motion_description: The user's motion request (e.g., "right arm out")
        joints: The proposed joint values

    Returns:
        List of warning messages for sign mismatches
    """
    warnings = []
    motion_lower = motion_description.lower()

    # === HEAD DIRECTION CHECKS ===
    neck_yaw = joints.get("neck_yaw")
    if neck_yaw is not None:
        # Check for "left" in head context
        head_left_patterns = ["head left", "head to the left", "turn left", "look left", "rotate left"]
        head_right_patterns = ["head right", "head to the right", "turn right", "look right", "rotate right"]

        is_head_left = any(p in motion_lower for p in head_left_patterns)
        is_head_right = any(p in motion_lower for p in head_right_patterns)

        if is_head_left and neck_yaw < 0:
            warnings.append(
                f"SIGN ERROR: HEAD LEFT should use POSITIVE neck_yaw "
                f"(got {neck_yaw:.2f}, should be positive like +1.0)"
            )
        elif is_head_right and neck_yaw > 0:
            warnings.append(
                f"SIGN ERROR: HEAD RIGHT should use NEGATIVE neck_yaw "
                f"(got +{neck_yaw:.2f}, should be negative like -1.0)"
            )

    # Detect "out" or "side" motion requests
    out_motion = any(word in motion_lower for word in ["out", "side", "sideways", "outward"])

    if out_motion:
        # RIGHT arm out should use NEGATIVE r_shoulder_aa
        if "right" in motion_lower and joints.get("r_shoulder_aa", 0) > 0:
            warnings.append(
                "SIGN ERROR: RIGHT arm out should use NEGATIVE r_shoulder_aa "
                f"(got +{joints['r_shoulder_aa']:.2f}, should be negative)"
            )

        # LEFT arm out should use POSITIVE l_shoulder_aa
        if "left" in motion_lower and joints.get("l_shoulder_aa", 0) < 0:
            warnings.append(
                "SIGN ERROR: LEFT arm out should use POSITIVE l_shoulder_aa "
                f"(got {joints['l_shoulder_aa']:.2f}, should be positive)"
            )

        # Both arms / plural "arms" - check both
        if "arms" in motion_lower or "both" in motion_lower:
            if joints.get("r_shoulder_aa", 0) > 0:
                warnings.append(
                    "SIGN ERROR: RIGHT arm out should use NEGATIVE r_shoulder_aa "
                    f"(got +{joints.get('r_shoulder_aa', 0):.2f})"
                )
            if joints.get("l_shoulder_aa", 0) < 0:
                warnings.append(
                    "SIGN ERROR: LEFT arm out should use POSITIVE l_shoulder_aa "
                    f"(got {joints.get('l_shoulder_aa', 0):.2f})"
                )

    # Detect "in" motion requests (toward body)
    in_motion = any(word in motion_lower for word in [" in", "inward", "toward"])

    if in_motion:
        # RIGHT arm in should use POSITIVE r_shoulder_aa
        if "right" in motion_lower and joints.get("r_shoulder_aa", 0) < -0.1:
            warnings.append(
                "SIGN ERROR: RIGHT arm in should use POSITIVE r_shoulder_aa"
            )

        # LEFT arm in should use NEGATIVE l_shoulder_aa
        if "left" in motion_lower and joints.get("l_shoulder_aa", 0) > 0.1:
            warnings.append(
                "SIGN ERROR: LEFT arm in should use NEGATIVE l_shoulder_aa"
            )

    return warnings


def describe_joint_state(joints: dict[str, float]) -> str:
    """Generate a semantic description of the current robot state.

    Converts raw joint values to human-readable descriptions.
    """
    descriptions = []

    # Right arm state
    r_shoulder_fe = joints.get("r_shoulder_fe", 0)
    r_shoulder_aa = joints.get("r_shoulder_aa", 0)
    r_elbow = joints.get("r_elbow", 0)

    if r_shoulder_fe < -1.0:
        if r_shoulder_aa < -1.0:
            descriptions.append("right arm raised outward (T-pose)")
        elif r_elbow < -0.5:
            descriptions.append("right arm raised forward with bent elbow")
        else:
            descriptions.append("right arm raised forward")
    elif abs(r_shoulder_fe) < 0.3 and abs(r_shoulder_aa) < 0.3:
        descriptions.append("right arm at rest")
    elif r_shoulder_aa < -0.5:
        descriptions.append("right arm extended outward")

    # Left arm state
    l_shoulder_fe = joints.get("l_shoulder_fe", 0)
    l_shoulder_aa = joints.get("l_shoulder_aa", 0)
    l_elbow = joints.get("l_elbow", 0)

    if l_shoulder_fe < -1.0:
        if l_shoulder_aa > 1.0:
            descriptions.append("left arm raised outward (T-pose)")
        elif l_elbow < -0.5:
            descriptions.append("left arm raised forward with bent elbow")
        else:
            descriptions.append("left arm raised forward")
    elif abs(l_shoulder_fe) < 0.3 and abs(l_shoulder_aa) < 0.3:
        descriptions.append("left arm at rest")
    elif l_shoulder_aa > 0.5:
        descriptions.append("left arm extended outward")

    # Head state
    neck_yaw = joints.get("neck_yaw", 0)
    neck_pitch = joints.get("neck_pitch", 0)

    if neck_yaw > 0.3:
        descriptions.append("looking left")
    elif neck_yaw < -0.3:
        descriptions.append("looking right")

    if neck_pitch > 0.2:
        descriptions.append("looking down")
    elif neck_pitch < -0.15:
        descriptions.append("looking up")

    # Torso state
    torso_yaw = joints.get("torso_yaw", 0)
    torso_pitch = joints.get("torso_pitch", 0)

    if abs(torso_yaw) > 0.3:
        direction = "right" if torso_yaw > 0 else "left"
        descriptions.append(f"torso rotated {direction}")

    if torso_pitch > 0.2:
        descriptions.append("leaning forward")
    elif torso_pitch < -0.15:
        descriptions.append("leaning back")

    if not descriptions:
        return "neutral standing position"

    return "; ".join(descriptions)
