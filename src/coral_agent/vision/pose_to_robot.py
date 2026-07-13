"""Map MediaPipe pose_world_landmarks + head pose to robot joint targets.

Mirror mode: person's right side (MediaPipe right_*) → robot's left arm/leg,
and vice versa. This makes the robot feel like a partner facing the user.

Arm angles are extracted in the torso-local frame so shoulder pitch and roll
are decoupled from each other and from any global torso rotation. Leg angles
use a separate pelvis frame (hip line × world-up) so they're decoupled from
torso lean — bending at the waist doesn't swing the robot's legs.

Mapped: arms (shoulder pitch/roll, elbow bend, forearm twist), head (pan,
tilt), and legs (hip pitch/roll, knee bend). Hip yaw is NOT mapped — rotating
the leg about its own long axis is invisible from the hip→knee landmarks
(same reason forearm twist needs the finger landmarks), and the foot
landmarks that could recover it are noisy and often out of frame. Grippers,
hip yaw, and ankles stay at neutral.
"""

from __future__ import annotations

import math
import time
from typing import Optional

import numpy as np

from coral_agent.robot.angle_utils import rad_to_servo_units
from coral_agent.robot.interface import ServoCommand
from coral_agent.robot.servo_config import SERVO_ID_MAP
from coral_agent.validation import JOINT_LIMITS

from . import geometry

# NOTE: OneEuroFilter is imported lazily inside JointAngleSmoother (see __init__)
# rather than at module load. Pulling it here would drag in pose_estimator ->
# mediapipe/cv2, but compute_joint_targets / targets_to_servo_commands only need
# `geometry` (numpy). Keeping the top-level import light lets the Pi robot_server
# reuse the retargeting without installing the full vision stack.

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
_LM_L_KNEE = geometry.LEFT_KNEE
_LM_R_KNEE = geometry.RIGHT_KNEE
_LM_L_ANKLE = geometry.LEFT_ANKLE
_LM_R_ANKLE = geometry.RIGHT_ANKLE

_VISIBILITY_THRESHOLD = 0.5

# World-up for the pelvis frame. MediaPipe pose_world_landmarks use Y-down
# (empirically established — Google doesn't document the axis directions),
# so up is -Y. Assumes a roughly level camera; a tilted camera biases leg
# angles by the tilt.
_WORLD_UP = np.array([0.0, -1.0, 0.0])

# Depth-gate threshold: if shoulder→elbow projects to less than this fraction of
# the frame, the arm is aligned with the optical axis and depth is unreliable.
_DEPTH_GATE_2D_FRACTION = 0.05

# Soft caps for head — robot's full range is ±2.09 rad but small motions look natural
_HEAD_PAN_CAP = math.radians(60)
_HEAD_TILT_CAP = math.radians(30)

# Stand-pose offsets (radians) — must match primitives.py / ainex.xml keyframe
_STAND_L_SHO_ROLL = -1.3614
_STAND_R_SHO_ROLL = 1.3614


class JointAngleSmoother:
    """Per-joint OneEuro filter applied after retargeting.

    Replaces the prior EMA-based PoseTargetSmoother. OneEuro is preferred because
    it's adaptive: low cutoff when still (kills jitter), high cutoff when moving
    (preserves responsiveness). Joints that disappear and reappear get a fresh
    filter so we don't blend across discontinuities.
    """

    def __init__(self, min_cutoff: float = 1.5, beta: float = 0.05):
        # Imported here (not at module top) so compute_joint_targets stays free of
        # the mediapipe/cv2 dependency chain that pose_estimator pulls in.
        from .pose_estimator import OneEuroFilter

        self._OneEuroFilter = OneEuroFilter
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
                self._filters[k] = self._OneEuroFilter(min_cutoff=self._min_cutoff, beta=self._beta)
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


def hips_detected(body_landmarks: list[dict]) -> bool:
    """True if both hips have world coords and pass the visibility gate.

    The torso frame (and therefore all arm retargeting) is anchored on the hips;
    when they drop below threshold compute_joint_targets can only map the head.
    Callers use this to ask the user to reframe rather than move head-only.
    """
    if len(body_landmarks) <= _LM_R_HIP:
        return False
    return all(
        _has_world(body_landmarks[i]) and _visible(body_landmarks[i])
        for i in (_LM_L_HIP, _LM_R_HIP)
    )


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


def _pelvis_frame_from(body: list[dict]):
    """Build pelvis frame from the hip world landmarks; returns None if either
    hip is missing world coords / visibility, or the frame is degenerate
    (hip line near-vertical — person not upright).
    """
    for idx in (_LM_L_HIP, _LM_R_HIP):
        lm = body[idx]
        if not _has_world(lm) or not _visible(lm):
            return None
    return geometry.pelvis_frame(
        geometry.world_xyz(body[_LM_L_HIP]),
        geometry.world_xyz(body[_LM_R_HIP]),
        _WORLD_UP,
    )


def _limb_depth_gated(proximal: dict, distal: dict) -> bool:
    """True if the limb segment projects into a tiny 2D segment (near optical
    axis) — depth is unreliable there. Used for shoulder→elbow and hip→knee."""
    p_img = geometry.image_xy(proximal)
    d_img = geometry.image_xy(distal)
    return geometry.arm_image_projection_short(p_img, d_img, _DEPTH_GATE_2D_FRACTION)


def compute_joint_targets(
    body_landmarks: list[dict],
    head_pose: Optional[dict],
) -> dict[str, float]:
    """Convert one frame of pose data into robot joint angles in radians.

    Mirror mapping: MediaPipe LEFT (person's left) → robot RIGHT arm/leg; vice
    versa. Returns a subset of joint names — only those with confident
    landmarks and non-degenerate viewing geometry.

    Leg sign conventions (sim frame: X forward, Y left, Z up — pinned by the
    hip body placement in ainex.xml; cross-checked against the STAND_LOW_PULSE
    hardware crouch in motions.py):
      l_hip_pitch: flexion (thigh forward) = negative; r_hip_pitch mirrored.
      l_hip_roll:  abduction (leg out) = negative;     r_hip_roll mirrored.
      l_knee:      flexion = positive;                 r_knee mirrored.
    """
    targets: dict[str, float] = {}

    if len(body_landmarks) > _LM_R_WRIST:

        # builds the torso frame used as the local coord system
        R_torso = _torso_frame_from(body_landmarks)

        if R_torso is not None:
            # Person's RIGHT side → robot's LEFT arm
            if all(
                _visible(body_landmarks[i]) and _has_world(body_landmarks[i])
                for i in (_LM_R_SHOULDER, _LM_R_ELBOW)
            ) and not _limb_depth_gated(body_landmarks[_LM_R_SHOULDER], body_landmarks[_LM_R_ELBOW]):
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
            ) and not _limb_depth_gated(body_landmarks[_LM_L_SHOULDER], body_landmarks[_LM_L_ELBOW]):
                sh = body_landmarks[_LM_L_SHOULDER]
                el = body_landmarks[_LM_L_ELBOW]

                # convert to torso frame coordinate space, then get the angles
                pitch, roll_abd = geometry.shoulder_pitch_roll(
                    geometry.world_xyz(sh), geometry.world_xyz(el), R_torso, side="left"
                )

                # clamp these angles to their limit
                targets["r_sho_pitch"] = _clamp_to_limits("r_sho_pitch", pitch)
                targets["r_sho_roll"] = _clamp_to_limits("r_sho_roll", _STAND_R_SHO_ROLL - roll_abd)


                # compute 3D bend angle between forearm and upperarm
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

    # ── Legs: hip pitch/roll from the pelvis frame, knee bend frame-free. ──
    # Anchored on the pelvis frame (hip line × world-up), NOT the torso frame,
    # so leaning at the waist doesn't read as the legs swinging. Hip yaw is
    # unobservable from hip→knee (rotation about the segment's own axis) and
    # is deliberately not emitted.
    if len(body_landmarks) > _LM_R_ANKLE:
        R_pelvis = _pelvis_frame_from(body_landmarks)

        if R_pelvis is not None:
            # Person's RIGHT leg → robot's LEFT leg
            if all(
                _visible(body_landmarks[i]) and _has_world(body_landmarks[i])
                for i in (_LM_R_HIP, _LM_R_KNEE)
            ) and not _limb_depth_gated(body_landmarks[_LM_R_HIP], body_landmarks[_LM_R_KNEE]):
                hp = body_landmarks[_LM_R_HIP]
                kn = body_landmarks[_LM_R_KNEE]
                pitch, roll_abd = geometry.hip_pitch_roll(
                    geometry.world_xyz(hp), geometry.world_xyz(kn), R_pelvis, side="right"
                )
                # Sim signs: left hip flexion = negative, left abduction = negative
                targets["l_hip_pitch"] = _clamp_to_limits("l_hip_pitch", -pitch)
                targets["l_hip_roll"] = _clamp_to_limits("l_hip_roll", -roll_abd)
                an = body_landmarks[_LM_R_ANKLE]
                if _visible(an) and _has_world(an):
                    bend = geometry.knee_bend(
                        geometry.world_xyz(hp),
                        geometry.world_xyz(kn),
                        geometry.world_xyz(an),
                    )
                    # Sim sign: left knee flexion = positive
                    targets["l_knee"] = _clamp_to_limits("l_knee", bend)

            # Person's LEFT leg → robot's RIGHT leg
            if all(
                _visible(body_landmarks[i]) and _has_world(body_landmarks[i])
                for i in (_LM_L_HIP, _LM_L_KNEE)
            ) and not _limb_depth_gated(body_landmarks[_LM_L_HIP], body_landmarks[_LM_L_KNEE]):
                hp = body_landmarks[_LM_L_HIP]
                kn = body_landmarks[_LM_L_KNEE]
                pitch, roll_abd = geometry.hip_pitch_roll(
                    geometry.world_xyz(hp), geometry.world_xyz(kn), R_pelvis, side="left"
                )
                # Mirrored sim signs: right hip flexion = positive, abduction = positive
                targets["r_hip_pitch"] = _clamp_to_limits("r_hip_pitch", pitch)
                targets["r_hip_roll"] = _clamp_to_limits("r_hip_roll", roll_abd)
                an = body_landmarks[_LM_L_ANKLE]
                if _visible(an) and _has_world(an):
                    bend = geometry.knee_bend(
                        geometry.world_xyz(hp),
                        geometry.world_xyz(kn),
                        geometry.world_xyz(an),
                    )
                    # Mirrored sim sign: right knee flexion = negative
                    targets["r_knee"] = _clamp_to_limits("r_knee", -bend)

    return targets


def targets_to_servo_commands(
    targets: dict[str, float], duration_ms: int
) -> list[ServoCommand]:
    """Convert joint-name → radians dict to ServoCommands for the *simulator*.

    Uses the uniform 500-centre map (rad=0 ↔ 500), which round-trips correctly
    through the MuJoCo sim. For the physical robot use
    targets_to_hardware_servo_commands instead — real servos have asymmetric
    stand pulses, mirror-mounted direction signs, and damaged-servo limits.
    """
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


def targets_to_hardware_servo_commands(
    targets: dict[str, float], duration_ms: int
) -> list[ServoCommand]:
    """Convert joint-name → radians dict to ServoCommands for the *physical robot*.

    This is the middle step the hardware /map-features needs: instead of the sim's
    uniform 500-centre map, each joint is converted with rad_to_hardware_units,
    which anchors on the joint's real STAND_PULSE, applies its mirror-mount
    direction sign, and clamps to the tested safe servo range (e.g. the damaged
    r_el_yaw is never driven below its floor). Mirrors the per-servo calibration
    used by the on-robot pose_mimic node.
    """
    # Imported here to keep the sim path free of any hardware-config coupling.
    from coral_agent.robot.hardware_angle_utils import rad_to_hardware_units

    commands: list[ServoCommand] = []
    for joint, rad in targets.items():
        servo_id = SERVO_ID_MAP.get(joint)
        if servo_id is None:
            continue
        commands.append(
            ServoCommand(
                servo_id=servo_id,
                position=rad_to_hardware_units(rad, joint),
                duration_ms=duration_ms,
            )
        )
    return commands
