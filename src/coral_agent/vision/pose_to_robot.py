"""Map MediaPipe pose_world_landmarks + head pose to robot joint targets.

Mirror mode: person's right side (MediaPipe right_*) → robot's left arm, and
vice versa. This makes the robot feel like a partner facing the user.

Joint angles are extracted in the torso-local frame so shoulder pitch and roll
are decoupled from each other and from any global torso rotation.

Only arms (shoulder pitch/roll, elbow yaw) + head (pan, tilt) are mapped.
Elbow pitch, grippers, and legs are left at neutral.
"""

from __future__ import annotations

import math
import time
from typing import Optional

from coral_agent.robot.angle_utils import rad_to_servo_units
from coral_agent.robot.interface import ServoCommand
from coral_agent.robot.servo_config import SERVO_ID_MAP
from coral_agent.validation import JOINT_LIMITS

from . import geometry
from .pose_estimator import OneEuroFilter

# MediaPipe pose landmark indices (re-exported from geometry for clarity)
_LM_L_SHOULDER = geometry.LEFT_SHOULDER
_LM_R_SHOULDER = geometry.RIGHT_SHOULDER
_LM_L_ELBOW = geometry.LEFT_ELBOW
_LM_R_ELBOW = geometry.RIGHT_ELBOW
_LM_L_WRIST = geometry.LEFT_WRIST
_LM_R_WRIST = geometry.RIGHT_WRIST
_LM_L_INDEX = geometry.LEFT_INDEX
_LM_R_INDEX = geometry.RIGHT_INDEX
_LM_L_PINKY = geometry.LEFT_PINKY
_LM_R_PINKY = geometry.RIGHT_PINKY
_LM_L_HIP = geometry.LEFT_HIP
_LM_R_HIP = geometry.RIGHT_HIP

_VISIBILITY_THRESHOLD = 0.5

# Depth-gate threshold: if shoulder→elbow projects to less than this fraction of
# the frame, the arm is aligned with the optical axis and depth is unreliable.
_DEPTH_GATE_2D_FRACTION = 0.05

# Soft caps for head — robot's full range is ±2.09 rad but small motions look natural
_HEAD_PAN_CAP = math.radians(60)
_HEAD_TILT_CAP = math.radians(30)

# Stand-pose offsets (radians) — must match primitives.py
_STAND_L_SHO_ROLL = -1.403
_STAND_R_SHO_ROLL = 1.403


class JointAngleSmoother:
    """Per-joint OneEuro filter applied after retargeting.

    Replaces the prior EMA-based PoseTargetSmoother. OneEuro is preferred because
    it's adaptive: low cutoff when still (kills jitter), high cutoff when moving
    (preserves responsiveness). Joints that disappear and reappear get a fresh
    filter so we don't blend across discontinuities.
    """

    def __init__(self, min_cutoff: float = 1.5, beta: float = 0.05):
        self._min_cutoff = min_cutoff
        self._beta = beta
        self._filters: dict[str, OneEuroFilter] = {}
        self._last_seen: dict[str, float] = {}

    def reset(self) -> None:
        self._filters.clear()
        self._last_seen.clear()

    def smooth(self, targets: dict[str, float]) -> dict[str, float]:
        now = time.time()
        out: dict[str, float] = {}
        for k, v in targets.items():
            # If joint was missing for >0.5s, restart its filter to avoid
            # smoothing across a discontinuity.
            if k not in self._filters or (now - self._last_seen.get(k, 0.0)) > 0.5:
                self._filters[k] = OneEuroFilter(min_cutoff=self._min_cutoff, beta=self._beta)
            out[k] = self._filters[k].filter(v, now)
            self._last_seen[k] = now
        return out


def _visible(lm: dict) -> bool:
    return lm.get("visibility", 1.0) >= _VISIBILITY_THRESHOLD


def _has_world(lm: dict) -> bool:
    return "xw" in lm


def _clamp_to_limits(joint: str, value: float) -> float:
    limit = JOINT_LIMITS.get(joint)
    return limit.clamp(value) if limit else value


def _torso_frame_from(body: list[dict]):
    """Build torso frame from world landmarks; returns None if any required
    landmark is missing world coords or visibility.
    """
    required = (_LM_L_SHOULDER, _LM_R_SHOULDER, _LM_L_HIP, _LM_R_HIP)
    for idx in required:
        lm = body[idx]
        if not _has_world(lm) or not _visible(lm):
            return None
    return geometry.torso_frame(
        geometry.world_xyz(body[_LM_L_SHOULDER]),
        geometry.world_xyz(body[_LM_R_SHOULDER]),
        geometry.world_xyz(body[_LM_L_HIP]),
        geometry.world_xyz(body[_LM_R_HIP]),
    )


def _arm_depth_gated(shoulder: dict, elbow: dict) -> bool:
    """True if the arm projects into a tiny 2D segment (near optical axis)."""
    sh_img = geometry.image_xy(shoulder)
    el_img = geometry.image_xy(elbow)
    return geometry.arm_image_projection_short(sh_img, el_img, _DEPTH_GATE_2D_FRACTION)


def compute_joint_targets(
    body_landmarks: list[dict],
    head_pose: Optional[dict],
) -> dict[str, float]:
    """Convert one frame of pose data into robot joint angles in radians.

    Mirror mapping: MediaPipe LEFT (person's left) → robot RIGHT arm; vice versa.
    Returns a subset of joint names — only those with confident landmarks and
    non-degenerate viewing geometry.
    """
    targets: dict[str, float] = {}

    if len(body_landmarks) > _LM_R_WRIST:
        R_torso = _torso_frame_from(body_landmarks)

        if R_torso is not None:
            # Person's RIGHT side → robot's LEFT arm
            if all(
                _visible(body_landmarks[i]) and _has_world(body_landmarks[i])
                for i in (_LM_R_SHOULDER, _LM_R_ELBOW)
            ) and not _arm_depth_gated(body_landmarks[_LM_R_SHOULDER], body_landmarks[_LM_R_ELBOW]):
                sh = body_landmarks[_LM_R_SHOULDER]
                el = body_landmarks[_LM_R_ELBOW]
                pitch, roll_abd = geometry.shoulder_pitch_roll(
                    geometry.world_xyz(sh), geometry.world_xyz(el), R_torso, side="right"
                )
                targets["l_sho_pitch"] = _clamp_to_limits("l_sho_pitch", pitch)
                targets["l_sho_roll"] = _clamp_to_limits("l_sho_roll", _STAND_L_SHO_ROLL + roll_abd)
                wr = body_landmarks[_LM_R_WRIST]
                if _visible(wr) and _has_world(wr):
                    bend = geometry.elbow_bend(
                        geometry.world_xyz(sh),
                        geometry.world_xyz(el),
                        geometry.world_xyz(wr),
                    )
                    targets["l_el_yaw"] = _clamp_to_limits("l_el_yaw", -bend)
                    idx_lm = body_landmarks[_LM_R_INDEX]
                    pky_lm = body_landmarks[_LM_R_PINKY]
                    if all(_visible(x) and _has_world(x) for x in (idx_lm, pky_lm)):
                        twist = geometry.forearm_twist(
                            geometry.world_xyz(el),
                            geometry.world_xyz(wr),
                            geometry.world_xyz(idx_lm),
                            geometry.world_xyz(pky_lm),
                            R_torso,
                            side="right",
                        )
                        if twist is not None:
                            targets["l_el_pitch"] = _clamp_to_limits("l_el_pitch", -twist)

            # Person's LEFT side → robot's RIGHT arm
            if all(
                _visible(body_landmarks[i]) and _has_world(body_landmarks[i])
                for i in (_LM_L_SHOULDER, _LM_L_ELBOW)
            ) and not _arm_depth_gated(body_landmarks[_LM_L_SHOULDER], body_landmarks[_LM_L_ELBOW]):
                sh = body_landmarks[_LM_L_SHOULDER]
                el = body_landmarks[_LM_L_ELBOW]
                pitch, roll_abd = geometry.shoulder_pitch_roll(
                    geometry.world_xyz(sh), geometry.world_xyz(el), R_torso, side="left"
                )
                targets["r_sho_pitch"] = _clamp_to_limits("r_sho_pitch", pitch)
                targets["r_sho_roll"] = _clamp_to_limits("r_sho_roll", _STAND_R_SHO_ROLL - roll_abd)
                wr = body_landmarks[_LM_L_WRIST]
                if _visible(wr) and _has_world(wr):
                    bend = geometry.elbow_bend(
                        geometry.world_xyz(sh),
                        geometry.world_xyz(el),
                        geometry.world_xyz(wr),
                    )
                    targets["r_el_yaw"] = _clamp_to_limits("r_el_yaw", bend)
                    idx_lm = body_landmarks[_LM_L_INDEX]
                    pky_lm = body_landmarks[_LM_L_PINKY]
                    if all(_visible(x) and _has_world(x) for x in (idx_lm, pky_lm)):
                        twist = geometry.forearm_twist(
                            geometry.world_xyz(el),
                            geometry.world_xyz(wr),
                            geometry.world_xyz(idx_lm),
                            geometry.world_xyz(pky_lm),
                            R_torso,
                            side="left",
                        )
                        if twist is not None:
                            targets["r_el_pitch"] = _clamp_to_limits("r_el_pitch", -twist)

    if head_pose is not None:
        yaw = math.radians(head_pose.get("yaw", 0.0))
        pitch = math.radians(head_pose.get("pitch", 0.0))
        targets["head_pan"] = _clamp_to_limits(
            "head_pan", max(-_HEAD_PAN_CAP, min(_HEAD_PAN_CAP, yaw))
        )
        targets["head_tilt"] = _clamp_to_limits(
            "head_tilt", max(-_HEAD_TILT_CAP, min(_HEAD_TILT_CAP, pitch))
        )

    return targets


def targets_to_servo_commands(
    targets: dict[str, float], duration_ms: int
) -> list[ServoCommand]:
    """Convert joint-name → radians dict to ServoCommands."""
    commands: list[ServoCommand] = []
    for joint, rad in targets.items():
        servo_id = SERVO_ID_MAP.get(joint)
        if servo_id is None:
            continue
        commands.append(
            ServoCommand(
                servo_id=servo_id,
                position=rad_to_servo_units(rad),
                duration_ms=duration_ms,
            )
        )
    return commands
