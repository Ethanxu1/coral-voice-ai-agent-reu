"""Vendored copy of the landmark -> joint -> hardware-servo retargeting pipeline.

Why vendored instead of imported: this file lives in the standalone `ainex_demo`
ROS package deployed to the Pi (see robot_server.py's module docstring), which
does not include the rest of the coral_agent monorepo on disk — only the pi/
subtree is copied over. robot_server.py already follows this pattern for
SERVO_ID/STAND_PULSE rather than importing coral_agent.robot.servo_config; this
module extends that same pattern to compute_joint_targets and the hardware
angle conversion, so /map-features works without a cross-package import.

Keep in sync with (source of truth for the actual algorithm):
    coral_agent/vision/pose_to_robot.py
    coral_agent/vision/geometry.py
    coral_agent/robot/hardware_angle_utils.py
    coral_agent/validation.py (JOINT_LIMITS — arm/head joints only, used here)
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np

# ── Servo identity + stand pulses (mirrors robot_server.py's SERVO_ID/STAND_PULSE,
# arm + head subset only — legs are never targeted by compute_joint_targets) ──
SERVO_ID: Dict[str, int] = {
    "l_sho_pitch": 13, "r_sho_pitch": 14,
    "l_sho_roll": 15,  "r_sho_roll": 16,
    "l_el_pitch": 17,  "r_el_pitch": 18,
    "l_el_yaw": 19,    "r_el_yaw": 20,
    "head_pan": 23,    "head_tilt": 24,
}

STAND_PULSE: Dict[str, int] = {
    "l_sho_pitch": 835, "r_sho_pitch": 165,
    "l_sho_roll": 830,  "r_sho_roll": 170,
    "l_el_pitch": 500,  "r_el_pitch": 500,
    "l_el_yaw": 150,    "r_el_yaw": 850,
    "head_pan": 500,    "head_tilt": 500,
}

# Ticks per radian — same for all HX-series servos (1000 units / 240 degrees).
TICKS_PER_RAD = 1000 / 240 * (180 / math.pi)

# Arm joints whose retargeting stand-pose radian isn't 0.0 (mirrors
# hardware_angle_utils.HW_STAND_RAD).
HW_STAND_RAD: Dict[str, float] = {
    "l_sho_roll": -1.403,
    "r_sho_roll": 1.403,
    "l_el_yaw": -1.226,
    "r_el_yaw": 1.226,
}

# +1: hardware pulse increases as retargeted radian increases; -1: opposite
# (mirrors hardware_angle_utils.HW_DIRECTION, arm+head entries only).
HW_DIRECTION: Dict[str, int] = {
    "l_sho_pitch": -1, "r_sho_pitch": +1,
    "l_sho_roll": -1,  "r_sho_roll": -1,
    "l_el_pitch": -1,  "r_el_pitch": +1,
    "l_el_yaw": +1,    "r_el_yaw": +1,
    "head_pan": -1,    "head_tilt": +1,
}

# Measured safe pulse ranges per joint (mirrors hardware_angle_utils.HW_SERVO_LIMITS).
HW_SERVO_LIMITS: Dict[str, Tuple[int, int]] = {
    "l_sho_pitch": (333, 835),
    "r_sho_pitch": (200, 773),
    "l_sho_roll":  (440, 800),
    "r_sho_roll":  (213, 613),
    "l_el_pitch":  (440, 653),
    "r_el_pitch":  (320, 560),
    "l_el_yaw":    (90, 360),
    "r_el_yaw":    (573, 880),
}


def rad_to_hardware_units(rad: float, joint_name: str) -> int:
    """Radians -> physical servo pulse, anchored on this joint's real stand pose."""
    stand_pulse = STAND_PULSE.get(joint_name, 500)
    stand_rad = HW_STAND_RAD.get(joint_name, 0.0)
    direction = HW_DIRECTION.get(joint_name, +1)

    delta = rad - stand_rad
    units = stand_pulse + round(delta * TICKS_PER_RAD * direction)

    lo, hi = HW_SERVO_LIMITS.get(joint_name, (0, 1000))
    return max(lo, min(hi, units))


class ServoCommand:
    __slots__ = ("servo_id", "position", "duration_ms")

    def __init__(self, servo_id: int, position: int, duration_ms: int):
        self.servo_id = servo_id
        self.position = position
        self.duration_ms = duration_ms


# ── Joint radian limits (mirrors validation.JOINT_LIMITS, arm+head only) ─────
_JOINT_RAD_LIMITS: Dict[str, Tuple[float, float]] = {
    joint: (-2.09, 2.09) for joint in SERVO_ID  # all arm+head joints share ±2.09
}


def _clamp_to_limits(joint: str, value: float) -> float:
    lo, hi = _JOINT_RAD_LIMITS.get(joint, (-2.09, 2.09))
    return max(lo, min(hi, value))


# ── Geometry (mirrors coral_agent.vision.geometry) ───────────────────────────
_LM_L_SHOULDER = 11
_LM_R_SHOULDER = 12
_LM_L_ELBOW = 13
_LM_R_ELBOW = 14
_LM_L_WRIST = 15
_LM_R_WRIST = 16
_LM_L_PINKY = 17
_LM_R_PINKY = 18
_LM_L_INDEX = 19
_LM_R_INDEX = 20
_LM_L_HIP = 23
_LM_R_HIP = 24

_VISIBILITY_THRESHOLD = 0.5
_DEPTH_GATE_2D_FRACTION = 0.05
_STAND_L_SHO_ROLL = -1.403
_STAND_R_SHO_ROLL = 1.403
_HEAD_PAN_CAP = math.radians(60)
_HEAD_TILT_CAP = math.radians(30)


def _world_xyz(lm: dict) -> np.ndarray:
    return np.array([lm["xw"], lm["yw"], lm["zw"]], dtype=np.float64)


def _image_xy(lm: dict) -> np.ndarray:
    return np.array([lm["x"], lm["y"]], dtype=np.float64)


def _torso_frame(l_sho_w, r_sho_w, l_hip_w, r_hip_w) -> np.ndarray:
    shoulder_mid = 0.5 * (l_sho_w + r_sho_w)
    hip_mid = 0.5 * (l_hip_w + r_hip_w)
    x_raw = l_sho_w - r_sho_w
    y_raw = shoulder_mid - hip_mid
    x_axis = x_raw / (np.linalg.norm(x_raw) + 1e-9)
    y_axis = y_raw - np.dot(y_raw, x_axis) * x_axis
    y_axis = y_axis / (np.linalg.norm(y_axis) + 1e-9)
    z_axis = np.cross(x_axis, y_axis)
    return np.column_stack([x_axis, y_axis, z_axis])


def _to_torso(v_world: np.ndarray, R_torso: np.ndarray) -> np.ndarray:
    return R_torso.T @ v_world


def _shoulder_pitch_roll(shoulder_w, elbow_w, R_torso, side: str) -> Tuple[float, float]:
    arm = elbow_w - shoulder_w
    arm_t = _to_torso(arm, R_torso)
    n = float(np.linalg.norm(arm_t))
    if n < 1e-6:
        return 0.0, 0.0
    v = arm_t / n
    sagittal = math.hypot(float(v[1]), float(v[2]))
    pitch = 0.0 if sagittal < 1e-6 else math.atan2(float(v[2]), -float(v[1]))
    lateral = float(v[0]) if side == "left" else -float(v[0])
    lateral = max(-1.0, min(1.0, lateral))
    roll_abd = math.asin(lateral)
    return pitch, roll_abd


def _elbow_bend(shoulder_w, elbow_w, wrist_w) -> float:
    upper = elbow_w - shoulder_w
    forearm = wrist_w - elbow_w
    nu = float(np.linalg.norm(upper))
    nf = float(np.linalg.norm(forearm))
    if nu < 1e-4 or nf < 1e-4:
        return 0.0
    cos_a = float(np.dot(upper, forearm)) / (nu * nf)
    cos_a = max(-1.0, min(1.0, cos_a))
    return math.acos(cos_a)


def _forearm_twist(elbow_w, wrist_w, index_w, pinky_w, R_torso, side: str) -> Optional[float]:
    forearm = wrist_w - elbow_w
    f_norm = float(np.linalg.norm(forearm))
    if f_norm < 1e-4:
        return None
    f = forearm / f_norm
    palm_across = index_w - pinky_w
    if float(np.linalg.norm(palm_across)) < 1e-4:
        return None
    p_perp = palm_across - np.dot(palm_across, f) * f
    p_norm = float(np.linalg.norm(p_perp))
    if p_norm < 1e-4:
        return None
    p_perp = p_perp / p_norm
    ref_perp = None
    for axis_col in (1, 2):
        ref = R_torso[:, axis_col]
        rp = ref - np.dot(ref, f) * f
        r_norm = float(np.linalg.norm(rp))
        if r_norm >= 1e-3:
            ref_perp = rp / r_norm
            break
    if ref_perp is None:
        return None
    cos_a = max(-1.0, min(1.0, float(np.dot(ref_perp, p_perp))))
    sin_a = float(np.dot(np.cross(ref_perp, p_perp), f))
    angle = math.atan2(sin_a, cos_a)
    if side == "right":
        angle = -angle
    return angle


def _arm_image_projection_short(sh_img, el_img, threshold: float = 0.05) -> bool:
    return float(np.linalg.norm(el_img - sh_img)) < threshold


def _visible(lm: dict) -> bool:
    return lm.get("visibility", 1.0) >= _VISIBILITY_THRESHOLD


def _has_world(lm: dict) -> bool:
    return "xw" in lm


def hips_detected(body_landmarks: List[dict]) -> bool:
    """True if both hips have world coords and pass the visibility gate.

    The torso frame (and therefore all arm retargeting) is anchored on the
    hips; when they drop below threshold, compute_joint_targets can only map
    the head. Callers use this to ask the user to reframe instead of moving
    head-only.
    """
    if len(body_landmarks) <= _LM_R_HIP:
        return False
    return all(
        _has_world(body_landmarks[i]) and _visible(body_landmarks[i])
        for i in (_LM_L_HIP, _LM_R_HIP)
    )


def _torso_frame_from(body: List[dict]) -> Optional[np.ndarray]:
    required = (_LM_L_SHOULDER, _LM_R_SHOULDER, _LM_L_HIP, _LM_R_HIP)
    for idx in required:
        lm = body[idx]
        if not _has_world(lm) or not _visible(lm):
            return None
    return _torso_frame(
        _world_xyz(body[_LM_L_SHOULDER]),
        _world_xyz(body[_LM_R_SHOULDER]),
        _world_xyz(body[_LM_L_HIP]),
        _world_xyz(body[_LM_R_HIP]),
    )


def _arm_depth_gated(shoulder: dict, elbow: dict) -> bool:
    return _arm_image_projection_short(_image_xy(shoulder), _image_xy(elbow), _DEPTH_GATE_2D_FRACTION)


def compute_joint_targets(
    body_landmarks: List[dict],
    head_pose: Optional[dict],
) -> Dict[str, float]:
    """Convert one frame of pose data into robot joint angles in radians.

    Mirror mapping: MediaPipe LEFT (person's left) -> robot RIGHT arm; vice versa.
    Returns a subset of joint names — only those with confident landmarks and
    non-degenerate viewing geometry.
    """
    targets: Dict[str, float] = {}

    if len(body_landmarks) > _LM_R_WRIST:
        R_torso = _torso_frame_from(body_landmarks)

        if R_torso is not None:
            # Person's RIGHT side -> robot's LEFT arm
            if all(
                _visible(body_landmarks[i]) and _has_world(body_landmarks[i])
                for i in (_LM_R_SHOULDER, _LM_R_ELBOW)
            ) and not _arm_depth_gated(body_landmarks[_LM_R_SHOULDER], body_landmarks[_LM_R_ELBOW]):
                sh = body_landmarks[_LM_R_SHOULDER]
                el = body_landmarks[_LM_R_ELBOW]
                pitch, roll_abd = _shoulder_pitch_roll(
                    _world_xyz(sh), _world_xyz(el), R_torso, side="right"
                )
                targets["l_sho_pitch"] = _clamp_to_limits("l_sho_pitch", pitch)
                targets["l_sho_roll"] = _clamp_to_limits("l_sho_roll", _STAND_L_SHO_ROLL + roll_abd)
                wr = body_landmarks[_LM_R_WRIST]
                if _visible(wr) and _has_world(wr):
                    bend = _elbow_bend(_world_xyz(sh), _world_xyz(el), _world_xyz(wr))
                    targets["l_el_yaw"] = _clamp_to_limits("l_el_yaw", -bend)
                    idx_lm = body_landmarks[_LM_R_INDEX]
                    pky_lm = body_landmarks[_LM_R_PINKY]
                    if all(_visible(x) and _has_world(x) for x in (idx_lm, pky_lm)):
                        twist = _forearm_twist(
                            _world_xyz(el), _world_xyz(wr), _world_xyz(idx_lm), _world_xyz(pky_lm),
                            R_torso, side="right",
                        )
                        if twist is not None:
                            targets["l_el_pitch"] = _clamp_to_limits("l_el_pitch", -twist)

            # Person's LEFT side -> robot's RIGHT arm
            if all(
                _visible(body_landmarks[i]) and _has_world(body_landmarks[i])
                for i in (_LM_L_SHOULDER, _LM_L_ELBOW)
            ) and not _arm_depth_gated(body_landmarks[_LM_L_SHOULDER], body_landmarks[_LM_L_ELBOW]):
                sh = body_landmarks[_LM_L_SHOULDER]
                el = body_landmarks[_LM_L_ELBOW]
                pitch, roll_abd = _shoulder_pitch_roll(
                    _world_xyz(sh), _world_xyz(el), R_torso, side="left"
                )
                targets["r_sho_pitch"] = _clamp_to_limits("r_sho_pitch", pitch)
                targets["r_sho_roll"] = _clamp_to_limits("r_sho_roll", _STAND_R_SHO_ROLL - roll_abd)
                wr = body_landmarks[_LM_L_WRIST]
                if _visible(wr) and _has_world(wr):
                    bend = _elbow_bend(_world_xyz(sh), _world_xyz(el), _world_xyz(wr))
                    targets["r_el_yaw"] = _clamp_to_limits("r_el_yaw", bend)
                    idx_lm = body_landmarks[_LM_L_INDEX]
                    pky_lm = body_landmarks[_LM_L_PINKY]
                    if all(_visible(x) and _has_world(x) for x in (idx_lm, pky_lm)):
                        twist = _forearm_twist(
                            _world_xyz(el), _world_xyz(wr), _world_xyz(idx_lm), _world_xyz(pky_lm),
                            R_torso, side="left",
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


def targets_to_hardware_servo_commands(
    targets: Dict[str, float], duration_ms: int
) -> List[ServoCommand]:
    """Convert joint-name -> radians dict to physical servo pulses, using the
    per-joint hardware calibration (stand anchor, mirror direction, safe range)."""
    commands: List[ServoCommand] = []
    for joint, rad in targets.items():
        servo_id = SERVO_ID.get(joint)
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
