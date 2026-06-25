"""Map MediaPipe pose landmarks + head pose to robot joint targets.

Mirror mode: person's right side (MediaPipe right_*) → robot's left arm, and
vice versa. This makes the robot feel like a partner facing the user.

Only arms (shoulder pitch/roll, elbow bend) + head (pan, tilt) are mapped.
Elbow yaw, grippers, and legs are left at neutral.
"""

from __future__ import annotations

import math
from typing import Optional

from coral_agent.robot.angle_utils import rad_to_servo_units
from coral_agent.robot.interface import ServoCommand
from coral_agent.robot.servo_config import SERVO_ID_MAP
from coral_agent.validation import JOINT_LIMITS

# MediaPipe pose landmark indices
_LM_L_SHOULDER = 11
_LM_R_SHOULDER = 12
_LM_L_ELBOW = 13
_LM_R_ELBOW = 14
_LM_L_WRIST = 15
_LM_R_WRIST = 16

_VISIBILITY_THRESHOLD = 0.5

# Soft caps for head — robot's full range is ±2.09 rad but small motions look natural
_HEAD_PAN_CAP = math.radians(60)
_HEAD_TILT_CAP = math.radians(30)

# Stand-pose offsets (radians) — must match primitives.py
_STAND_L_SHO_ROLL = -1.403
_STAND_R_SHO_ROLL = 1.403


class PoseTargetSmoother:
    """Exponential moving average over per-joint targets to absorb 15→10 Hz jitter."""

    def __init__(self, alpha: float = 0.4):
        self.alpha = alpha
        self._prev: dict[str, float] = {}

    def reset(self) -> None:
        self._prev.clear()

    def smooth(self, targets: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for k, v in targets.items():
            prev = self._prev.get(k)
            out[k] = v if prev is None else (self.alpha * v + (1 - self.alpha) * prev)
        self._prev = out
        return out


def _vec(a: dict, b: dict) -> tuple[float, float, float]:
    return (b["x"] - a["x"], b["y"] - a["y"], b["z"] - a["z"])


def _norm(v: tuple[float, float, float]) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _visible(lm: dict) -> bool:
    return lm.get("visibility", 1.0) >= _VISIBILITY_THRESHOLD


def _clamp_to_limits(joint: str, value: float) -> float:
    limit = JOINT_LIMITS.get(joint)
    return limit.clamp(value) if limit else value


def _shoulder_pitch(shoulder: dict, elbow: dict) -> float:
    """Forward-flexion angle. Arm hanging = 0, arm forward = ~π/2, overhead = ~π."""
    _, dy, dz = _vec(shoulder, elbow)
    return math.atan2(-dz, max(dy, 1e-6))


def _shoulder_roll_abduction(shoulder: dict, elbow: dict) -> float:
    """Positive abduction magnitude (0 = arm at side, π/2 = arm out horizontally)."""
    dx, dy, _ = _vec(shoulder, elbow)
    return math.atan2(abs(dx), max(dy, 1e-6))


def _elbow_bend(shoulder: dict, elbow: dict, wrist: dict) -> float:
    """Angle between upper arm and forearm. 0 = straight, π = fully folded."""
    upper = _vec(shoulder, elbow)
    forearm = _vec(elbow, wrist)
    nu = _norm(upper)
    nf = _norm(forearm)
    if nu < 1e-4 or nf < 1e-4:
        return 0.0
    cos_a = _dot(upper, forearm) / (nu * nf)
    cos_a = max(-1.0, min(1.0, cos_a))
    return math.acos(cos_a)


def compute_joint_targets(
    body_landmarks: list[dict],
    head_pose: Optional[dict],
) -> dict[str, float]:
    """Convert one frame of pose data into robot joint angles in radians.

    Mirror mapping: MediaPipe LEFT (person's left) → robot RIGHT arm; vice versa.
    Returns a subset of joint names — only those with confident landmarks.
    """
    targets: dict[str, float] = {}

    if len(body_landmarks) > _LM_R_WRIST:
        # Person's RIGHT side → robot's LEFT arm
        if all(_visible(body_landmarks[i]) for i in (_LM_R_SHOULDER, _LM_R_ELBOW)):
            sh = body_landmarks[_LM_R_SHOULDER]
            el = body_landmarks[_LM_R_ELBOW]
            targets["l_sho_pitch"] = _clamp_to_limits("l_sho_pitch", _shoulder_pitch(sh, el))
            roll_abd = _shoulder_roll_abduction(sh, el)
            targets["l_sho_roll"] = _clamp_to_limits("l_sho_roll", _STAND_L_SHO_ROLL + roll_abd)
            if _visible(body_landmarks[_LM_R_WRIST]):
                wr = body_landmarks[_LM_R_WRIST]
                targets["l_el_yaw"] = _clamp_to_limits("l_el_yaw", -_elbow_bend(sh, el, wr))

        # Person's LEFT side → robot's RIGHT arm
        if all(_visible(body_landmarks[i]) for i in (_LM_L_SHOULDER, _LM_L_ELBOW)):
            sh = body_landmarks[_LM_L_SHOULDER]
            el = body_landmarks[_LM_L_ELBOW]
            targets["r_sho_pitch"] = _clamp_to_limits("r_sho_pitch", _shoulder_pitch(sh, el))
            roll_abd = _shoulder_roll_abduction(sh, el)
            targets["r_sho_roll"] = _clamp_to_limits("r_sho_roll", _STAND_R_SHO_ROLL - roll_abd)
            if _visible(body_landmarks[_LM_L_WRIST]):
                wr = body_landmarks[_LM_L_WRIST]
                targets["r_el_yaw"] = _clamp_to_limits("r_el_yaw", _elbow_bend(sh, el, wr))

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
