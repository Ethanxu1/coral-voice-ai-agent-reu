"""Joint limit validation for waypoints.

Validates waypoints before execution, auto-clamping out-of-range values with warnings.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from app.robot.hardware_angle_utils import HW_SERVO_LIMITS, hardware_units_to_rad

if TYPE_CHECKING:
    pass


@dataclass
class JointLimit:
    """Joint limit bounds."""

    min: float
    max: float

    def clamp(self, value: float) -> float:
        return max(self.min, min(self.max, value))

    def is_valid(self, value: float) -> bool:
        return self.min <= value <= self.max


def _from_hw(joint: str) -> JointLimit:
    """Sim-radian limit derived from the joint's hardware pulse range.

    hardware_units_to_rad applies the per-joint stand anchor + direction, so
    the endpoint order can flip for mirrored joints — sort before building.
    """
    lo_pulse, hi_pulse = HW_SERVO_LIMITS[joint]
    a = hardware_units_to_rad(lo_pulse, joint)
    b = hardware_units_to_rad(hi_pulse, joint)
    return JointLimit(min(a, b), max(a, b))


# Joint limits in sim radians. Every hardware-limited servo (arms, legs,
# ankles) is DERIVED from hardware_angle_utils.HW_SERVO_LIMITS — the single
# source of truth — so the sim clamps exactly where the physical servos clamp
# and poses can't diverge between the two. Edit the pulse ranges there, not
# radians here.
#
# Head and grippers have no hardware-swept pulse range, so they keep the
# hand-authored ainex.xml default of ±2.09 rad (±120°).
# Sign conventions (sim frame): l_hip_pitch flexion = −, l_hip_roll abduction
# = −, l_knee flexion = +; right side mirrored. See pose_to_robot.py.
JOINT_LIMITS: dict[str, JointLimit] = {
    # Head
    "head_pan": JointLimit(-2.09, 2.09),
    "head_tilt": JointLimit(-2.09, 2.09),
    # Grippers
    "l_gripper": JointLimit(-2.09, 2.09),
    "r_gripper": JointLimit(-2.09, 2.09),
    # Arms, legs, ankles — derived from the hardware pulse limits.
    **{joint: _from_hw(joint) for joint in HW_SERVO_LIMITS},
}


@dataclass
class ValidationResult:
    original_joints: dict[str, float]
    validated_joints: dict[str, float]
    violations: list[str]
    unknown_joints: list[str]

    @property
    def had_violations(self) -> bool:
        return len(self.violations) > 0 or len(self.unknown_joints) > 0


def validate_waypoint(joints: dict[str, float], clamp: bool = True) -> ValidationResult:
    """Validate and optionally clamp joint values."""
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
                continue
        else:
            validated[joint_name] = value

    return ValidationResult(
        original_joints=joints,
        validated_joints=validated,
        violations=violations,
        unknown_joints=unknown_joints,
    )


def describe_joint_state(joints: dict[str, float]) -> str:
    """Generate a semantic description of the current robot state."""
    descriptions = []

    # Right arm state
    r_sho_pitch = joints.get("r_sho_pitch", 0)
    r_sho_roll = joints.get("r_sho_roll", 1.4)  # 1.4 is stand default
    r_el_pitch = joints.get("r_el_pitch", 0)

    if r_sho_pitch > 1.0:
        if r_sho_roll < 0.5:
            descriptions.append("right arm raised outward (T-pose)")
        elif r_el_pitch < -0.5:
            descriptions.append("right arm raised forward with bent elbow")
        else:
            descriptions.append("right arm raised forward")
    elif abs(r_sho_pitch) < 0.3 and abs(r_sho_roll - 1.4) < 0.3:
        descriptions.append("right arm at rest")
    elif r_sho_roll < 0.5:
        descriptions.append("right arm extended outward")

    # Left arm state
    l_sho_pitch = joints.get("l_sho_pitch", 0)
    l_sho_roll = joints.get("l_sho_roll", -1.4)  # -1.4 is stand default
    l_el_pitch = joints.get("l_el_pitch", 0)

    if l_sho_pitch > 1.0:
        if l_sho_roll > -0.5:
            descriptions.append("left arm raised outward (T-pose)")
        elif l_el_pitch < -0.5:
            descriptions.append("left arm raised forward with bent elbow")
        else:
            descriptions.append("left arm raised forward")
    elif abs(l_sho_pitch) < 0.3 and abs(l_sho_roll + 1.4) < 0.3:
        descriptions.append("left arm at rest")
    elif l_sho_roll > -0.5:
        descriptions.append("left arm extended outward")

    # Head state
    head_pan = joints.get("head_pan", 0)
    head_tilt = joints.get("head_tilt", 0)

    if head_pan < -0.3:
        descriptions.append("looking left")
    elif head_pan > 0.3:
        descriptions.append("looking right")

    if head_tilt > 0.2:
        descriptions.append("looking up")
    elif head_tilt < -0.2:
        descriptions.append("looking down")

    if not descriptions:
        return "neutral standing position"

    return "; ".join(descriptions)
