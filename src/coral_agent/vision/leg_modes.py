"""Selectable leg-retargeting strategies for the sim demo's /map-features.

Three modes, chosen per request:

  "retarget"  (default) — the current pelvis-frame leg retargeting in
                pose_to_robot.compute_joint_targets. Nothing here; the caller
                just uses compute_joint_targets unchanged.

  "legacy"    — a faithful port of the old pose_mimic_3d.compute_leg_pulses:
                drives hip_yaw (11/12) from forward/backward thigh swing and
                hip_roll (9/10) from lateral tilt, via atan2 on raw MediaPipe
                world axes. This is the ANATOMICALLY WRONG mapping documented
                in that node (sagittal swing sent to the yaw joint), preserved
                on purpose so the two behaviours can be compared side by side.

  "classify"  — run the MobileNetV3 pose classifier, then take ALL leg servos
                (IDs 1-12) from the matching canned pose in robot.motions. The
                legs snap to that class's stance; the arms keep the live
                retargeting.

Modes 2 and 3 are authored in *hardware* servo pulses (the units the old node
and motions.py use). This module converts those pulses back to sim radians with
hardware_units_to_rad — exactly how server._play_sim_motion renders canned poses
in the sim — so the values land at the right MuJoCo angles despite the joints
whose hardware neutral isn't 500 (hip_pitch, ankles). The caller then runs the
merged radian dict through targets_to_servo_commands like any other frame.
"""

from __future__ import annotations

import math
from typing import Dict, Literal

import numpy as np

from coral_agent.robot.hardware_angle_utils import hardware_units_to_rad
from coral_agent.robot.servo_config import STAND_PULSE

from . import geometry

LegMode = Literal["retarget", "legacy", "classify"]
LEG_MODES: tuple[str, ...] = ("retarget", "legacy", "classify")

# The 12 leg joints (servo IDs 1-12). Used both to strip pelvis-frame legs out
# of a compute_joint_targets result and to pull leg servos from a canned pose.
LEG_JOINTS: tuple[str, ...] = (
    "l_ank_roll", "r_ank_roll",
    "l_ank_pitch", "r_ank_pitch",
    "l_knee", "r_knee",
    "l_hip_pitch", "r_hip_pitch",
    "l_hip_roll", "r_hip_roll",
    "l_hip_yaw", "r_hip_yaw",
)

# ── Class → canned pose (mode 3) ────────────────────────────────────────────
# The 7 classifier labels each name a single-frame pose in robot.motions with
# the same key. Resolved lazily so importing this module stays torch-free.
_CLASS_TO_MOTION = {
    "dab": "dab",
    "hand-raised": "hand-raised",
    "muscles": "muscles",
    "superhero": "superhero",
    "t-pose": "t-pose",
    "thinker": "thinker",
    "warrior2": "warrior2",
}


def strip_legs(targets: Dict[str, float]) -> Dict[str, float]:
    """Return `targets` without any leg joints (keeps arms + head)."""
    return {k: v for k, v in targets.items() if k not in LEG_JOINTS}


def leg_pulses_to_targets(leg_pulses: Dict[str, int]) -> Dict[str, float]:
    """Convert a {leg_joint: hardware_pulse} dict to {leg_joint: sim_radians}.

    Inverts each joint's hardware calibration (stand-pulse anchor + mirror-mount
    direction) so a pose authored in hardware units renders at the right sim
    angle — the same conversion server._play_sim_motion uses for canned motions.
    """
    return {
        joint: hardware_units_to_rad(int(pulse), joint)
        for joint, pulse in leg_pulses.items()
        if joint in LEG_JOINTS
    }


# ── Mode 2: legacy atan2 leg pulses ─────────────────────────────────────────
_UNITS_PER_DEG = 1000.0 / 240.0  # ≈ 4.17, matches the old node


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def legacy_leg_pulses(body_landmarks: list[dict]) -> Dict[str, int]:
    """Port of pose_mimic_3d.compute_leg_pulses — the deliberately-wrong mapping.

    Drives only hip_yaw (11/12) from sagittal swing and hip_roll (9/10) from
    lateral tilt; every other leg servo is held at its stand pulse. Returns all
    12 leg joints so the stance is fully specified. Falls back to a full stand
    stance if the hip/knee world landmarks aren't available.

    Landmark world coords come straight from the dicts (xw/yw/zw); the axis
    assumptions (Y-down, +Z toward the person's back) and the flipped-image
    left/right identity are inherited verbatim from the old node.
    """
    pulses: Dict[str, int] = {j: STAND_PULSE[j] for j in LEG_JOINTS}

    def _world(i: int):
        lm = body_landmarks[i] if i < len(body_landmarks) else None
        if not lm or "xw" not in lm:
            return None
        return np.array([lm["xw"], lm["yw"], lm["zw"]], dtype=np.float64)

    l_hip = _world(geometry.LEFT_HIP)
    r_hip = _world(geometry.RIGHT_HIP)
    l_knee = _world(geometry.LEFT_KNEE)
    r_knee = _world(geometry.RIGHT_KNEE)
    if any(v is None for v in (l_hip, r_hip, l_knee, r_knee)):
        return pulses

    l_upper_leg = l_knee - l_hip
    r_upper_leg = r_knee - r_hip

    # Hip yaw (servo 11/12): forward/backward leg swing — atan2(-Z, Y).
    l_yaw = math.degrees(math.atan2(-l_upper_leg[2], l_upper_leg[1]))
    r_yaw = math.degrees(math.atan2(-r_upper_leg[2], r_upper_leg[1]))
    l_yaw = _clamp(l_yaw, -20, 45)
    r_yaw = _clamp(r_yaw, -20, 45)
    pulses["l_hip_yaw"] = int(_clamp(STAND_PULSE["l_hip_yaw"] - l_yaw * _UNITS_PER_DEG, 300, 600))
    pulses["r_hip_yaw"] = int(_clamp(STAND_PULSE["r_hip_yaw"] + r_yaw * _UNITS_PER_DEG, 400, 700))

    # Hip roll (servo 9/10): lateral leg tilt — atan2(X, Y).
    l_roll = math.degrees(math.atan2(l_upper_leg[0], l_upper_leg[1]))
    r_roll = math.degrees(math.atan2(r_upper_leg[0], r_upper_leg[1]))
    l_roll = _clamp(l_roll, -30, 20)
    r_roll = _clamp(r_roll, -20, 30)
    pulses["l_hip_roll"] = int(_clamp(STAND_PULSE["l_hip_roll"] + l_roll * _UNITS_PER_DEG, 400, 600))
    pulses["r_hip_roll"] = int(_clamp(STAND_PULSE["r_hip_roll"] + r_roll * _UNITS_PER_DEG, 400, 600))

    return pulses


# ── Mode 3: classified canned-pose leg pulses ───────────────────────────────
def classify_leg_pulses(class_name: str) -> Dict[str, int]:
    """Return the 12 leg-servo hardware pulses from the canned pose for
    `class_name`. Unknown class → full stand stance (safe no-op)."""
    from coral_agent.robot import motions

    motion_name = _CLASS_TO_MOTION.get(class_name)
    if motion_name is None:
        return {j: STAND_PULSE[j] for j in LEG_JOINTS}
    sequence = motions.get_motion(motion_name)
    if not sequence:
        return {j: STAND_PULSE[j] for j in LEG_JOINTS}
    pose = sequence[0][0]  # single-frame pose: (pulse_dict, duration)
    return {j: int(pose.get(j, STAND_PULSE[j])) for j in LEG_JOINTS}
