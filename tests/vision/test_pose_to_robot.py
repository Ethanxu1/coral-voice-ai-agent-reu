"""End-to-end tests for compute_joint_targets: synthetic landmarks → joint dict.

Verifies the full pipeline (depth gate + visibility check + rotation extraction
+ mirror mode + STAND offset + clamping) produces sensible servo targets for
canonical poses.

World-coordinate convention in this file matches real MediaPipe
pose_world_landmarks (empirically established, undocumented by Google):
  +x = person's left (anatomical)
  +y = DOWN
  +z = away from the camera (person faces the camera, so forward = -z)
Hips at y=0, shoulders at y≈-0.5, knees/ankles at positive y. The torso frame
is derived from the landmarks themselves so arm results don't depend on this
choice, but the pelvis frame hardcodes world-up = -y (pose_to_robot._WORLD_UP),
so LEG world coordinates must follow the real convention.
"""

from __future__ import annotations

import math

import pytest

from robot.hardware_angle_utils import HW_STAND_RAD
from validation import JOINT_LIMITS
from vision.pose_to_robot import (
    _STAND_L_SHO_ROLL,
    _STAND_R_SHO_ROLL,
    compute_joint_targets,
)


def _empty_landmark() -> dict:
    return {"x": 0.5, "y": 0.5, "z": 0.0, "visibility": 0.0,
            "xw": 0.0, "yw": 0.0, "zw": 0.0}


def _build_body(
    *,
    l_sho=(+0.2, -0.5, 0.0),
    r_sho=(-0.2, -0.5, 0.0),
    l_hip=(+0.1, 0.0, 0.0),
    r_hip=(-0.1, 0.0, 0.0),
    l_elbow=(+0.2, -0.2, 0.0),  # default = arms-down rest (elbow below shoulder)
    r_elbow=(-0.2, -0.2, 0.0),
    l_wrist=(+0.2, +0.1, 0.0),
    r_wrist=(-0.2, +0.1, 0.0),
    l_pinky=None,
    r_pinky=None,
    l_index=None,
    r_index=None,
    l_knee=(+0.1, +0.4, 0.0),  # default = standing (knee straight below hip)
    r_knee=(-0.1, +0.4, 0.0),
    l_ankle=(+0.1, +0.8, 0.0),
    r_ankle=(-0.1, +0.8, 0.0),
    img_l_sho=(0.62, 0.40),
    img_r_sho=(0.38, 0.40),
    img_l_elbow=(0.75, 0.55),
    img_r_elbow=(0.25, 0.55),
    img_l_wrist=(0.85, 0.65),
    img_r_wrist=(0.15, 0.65),
    img_l_knee=(0.55, 0.78),
    img_r_knee=(0.45, 0.78),
    img_l_ankle=(0.55, 0.92),
    img_r_ankle=(0.45, 0.92),
) -> list[dict]:
    body = [_empty_landmark() for _ in range(33)]

    def set_pt(i, w, img=None):
        body[i]["xw"], body[i]["yw"], body[i]["zw"] = w
        body[i]["visibility"] = 1.0
        if img is not None:
            body[i]["x"], body[i]["y"] = img

    set_pt(11, l_sho, img_l_sho)
    set_pt(12, r_sho, img_r_sho)
    set_pt(13, l_elbow, img_l_elbow)
    set_pt(14, r_elbow, img_r_elbow)
    set_pt(15, l_wrist, img_l_wrist)
    set_pt(16, r_wrist, img_r_wrist)
    if l_pinky is not None:
        set_pt(17, l_pinky, img_l_wrist)
    if r_pinky is not None:
        set_pt(18, r_pinky, img_r_wrist)
    if l_index is not None:
        set_pt(19, l_index, img_l_wrist)
    if r_index is not None:
        set_pt(20, r_index, img_r_wrist)
    set_pt(23, l_hip, (0.55, 0.65))
    set_pt(24, r_hip, (0.45, 0.65))
    set_pt(25, l_knee, img_l_knee)
    set_pt(26, r_knee, img_r_knee)
    set_pt(27, l_ankle, img_l_ankle)
    set_pt(28, r_ankle, img_r_ankle)
    # nose + ears so any head consumer doesn't crash
    set_pt(0, (0.0, -0.7, -0.1), (0.5, 0.30))
    set_pt(7, (+0.08, -0.65, 0.0), (0.56, 0.32))
    set_pt(8, (-0.08, -0.65, 0.0), (0.44, 0.32))
    return body


def test_t_pose_targets():
    """Both arms abducted to T → l_sho_roll and r_sho_roll both move from
    STAND offset toward 0 by ~π/2; pitches near 0."""
    body = _build_body(
        l_elbow=(+0.5, -0.5, 0.0),
        r_elbow=(-0.5, -0.5, 0.0),
        l_wrist=(+0.8, -0.5, 0.0),
        r_wrist=(-0.8, -0.5, 0.0),
        img_l_elbow=(0.85, 0.40),
        img_r_elbow=(0.15, 0.40),
        img_l_wrist=(0.98, 0.40),
        img_r_wrist=(0.02, 0.40),
    )
    targets = compute_joint_targets(body, head_pose=None)

    # Mirror: person's right arm → robot's left
    assert "l_sho_pitch" in targets and "l_sho_roll" in targets
    assert "r_sho_pitch" in targets and "r_sho_roll" in targets

    assert abs(targets["l_sho_pitch"]) < 1e-3
    assert abs(targets["r_sho_pitch"]) < 1e-3

    # STAND_L_SHO_ROLL = -1.403; adding π/2 (≈1.5708) gives ≈0.168
    assert targets["l_sho_roll"] == pytest.approx(_STAND_L_SHO_ROLL + math.pi / 2, abs=1e-3)
    assert targets["r_sho_roll"] == pytest.approx(_STAND_R_SHO_ROLL - math.pi / 2, abs=1e-3)

    # Elbows extended → bend target 0, but the hardware-derived elbow ranges
    # can't reach a fully straight arm, so the target clamps to the bound.
    assert targets["l_el_yaw"] == pytest.approx(JOINT_LIMITS["l_el_yaw"].clamp(0.0), abs=1e-3)
    assert targets["r_el_yaw"] == pytest.approx(JOINT_LIMITS["r_el_yaw"].clamp(0.0), abs=1e-3)


def test_rest_pose_targets():
    """Arms hanging at sides → roll stays at STAND offset, pitch=0."""
    body = _build_body()  # defaults are rest pose
    targets = compute_joint_targets(body, head_pose=None)

    assert targets["l_sho_pitch"] == pytest.approx(0.0, abs=1e-3)
    assert targets["r_sho_pitch"] == pytest.approx(0.0, abs=1e-3)
    assert targets["l_sho_roll"] == pytest.approx(_STAND_L_SHO_ROLL, abs=1e-3)
    assert targets["r_sho_roll"] == pytest.approx(_STAND_R_SHO_ROLL, abs=1e-3)


def test_arms_forward_depth_gate_suppresses_targets():
    """Arms point straight at camera → image projection short → depth gate
    triggers → arm targets are NOT emitted (frozen at last good state)."""
    body = _build_body(
        l_elbow=(+0.2, -0.5, -0.3),  # 0.3m toward camera from shoulder
        r_elbow=(-0.2, -0.5, -0.3),
        l_wrist=(+0.2, -0.5, -0.6),
        r_wrist=(-0.2, -0.5, -0.6),
        # Image: shoulder and elbow nearly coincide (arm along optical axis)
        img_l_elbow=(0.625, 0.405),
        img_r_elbow=(0.375, 0.405),
        img_l_wrist=(0.628, 0.408),
        img_r_wrist=(0.372, 0.408),
    )
    targets = compute_joint_targets(body, head_pose=None)
    assert "l_sho_pitch" not in targets
    assert "r_sho_pitch" not in targets


def test_low_visibility_suppresses_arm():
    """Right elbow hidden → robot left arm omitted (mirror), robot right still
    emitted. (Torso frame stays valid because both shoulders + hips visible.)"""
    body = _build_body()
    body[14]["visibility"] = 0.1  # right elbow hidden
    targets = compute_joint_targets(body, head_pose=None)
    assert "l_sho_pitch" not in targets  # robot left mirrors person's right
    assert "r_sho_pitch" in targets


def test_missing_shoulder_disables_both_arms():
    """Either shoulder hidden → torso frame unbuildable → both arms suppressed.
    Legs are unaffected: the pelvis frame only needs the hips."""
    body = _build_body()
    body[12]["visibility"] = 0.1
    targets = compute_joint_targets(body, head_pose=None)
    assert "l_sho_pitch" not in targets
    assert "r_sho_pitch" not in targets
    assert "l_hip_pitch" in targets
    assert "r_hip_pitch" in targets


def test_forearm_twist_emits_el_pitch_when_hand_landmarks_present():
    """Both arms in T-pose with palm-down hands → l_el_pitch / r_el_pitch
    are emitted and finite (sign is convention-defined; here we just verify
    the joints make it through the pipeline with hand landmarks)."""
    body = _build_body(
        l_elbow=(+0.5, -0.5, 0.0),
        r_elbow=(-0.5, -0.5, 0.0),
        l_wrist=(+0.8, -0.5, 0.0),
        r_wrist=(-0.8, -0.5, 0.0),
        l_pinky=(+0.8, -0.5, +0.05),
        r_pinky=(-0.8, -0.5, +0.05),
        l_index=(+0.8, -0.5, -0.05),
        r_index=(-0.8, -0.5, -0.05),
        img_l_elbow=(0.85, 0.40),
        img_r_elbow=(0.15, 0.40),
        img_l_wrist=(0.98, 0.40),
        img_r_wrist=(0.02, 0.40),
    )
    targets = compute_joint_targets(body, head_pose=None)
    assert "l_el_pitch" in targets
    assert "r_el_pitch" in targets
    # Palm-down twists past both forearm servos' hardware ranges, so each side
    # clamps to its own derived bound (the ranges are asymmetric, so the two
    # sides no longer land on equal values).
    assert targets["l_el_pitch"] == pytest.approx(JOINT_LIMITS["l_el_pitch"].min, abs=1e-3)
    assert targets["r_el_pitch"] == pytest.approx(JOINT_LIMITS["r_el_pitch"].min, abs=1e-3)


def test_forearm_twist_omitted_when_hand_landmarks_missing():
    """Hand landmarks invisible (visibility=0 by default) → twist omitted,
    rest of the arm targets still emitted."""
    body = _build_body(
        l_elbow=(+0.5, -0.5, 0.0),
        r_elbow=(-0.5, -0.5, 0.0),
        l_wrist=(+0.8, -0.5, 0.0),
        r_wrist=(-0.8, -0.5, 0.0),
        img_l_elbow=(0.85, 0.40),
        img_r_elbow=(0.15, 0.40),
        img_l_wrist=(0.98, 0.40),
        img_r_wrist=(0.02, 0.40),
    )
    targets = compute_joint_targets(body, head_pose=None)
    assert "l_sho_pitch" in targets
    assert "l_el_pitch" not in targets
    assert "r_el_pitch" not in targets


def test_head_pan_tilt_clamps_to_caps():
    """Head pose in degrees beyond the soft cap is clamped."""
    body = _build_body()
    head = {"yaw": 90.0, "pitch": 60.0, "roll": 0.0}
    targets = compute_joint_targets(body, head_pose=head)
    # 60° pan cap, 30° tilt cap (defined in pose_to_robot)
    assert targets["head_pan"] == pytest.approx(math.radians(60), abs=1e-3)
    assert targets["head_tilt"] == pytest.approx(math.radians(30), abs=1e-3)


# ── Legs ───────────────────────────────────────────────────────────────────────


def test_standing_legs_neutral():
    """Legs straight down → all six leg targets emitted at the clamp of 0.

    The hardware-derived hip-pitch/knee ranges don't include a fully straight
    leg (the robot always stands slightly bent), so 0 rad clamps to the nearest
    bound; hip_roll's range contains 0 and stays exactly neutral."""
    body = _build_body()  # defaults are standing
    targets = compute_joint_targets(body, head_pose=None)
    for joint in ("l_hip_pitch", "r_hip_pitch", "l_hip_roll", "r_hip_roll",
                  "l_knee", "r_knee"):
        assert targets[joint] == pytest.approx(JOINT_LIMITS[joint].clamp(0.0), abs=1e-3), joint


def test_knee_raise_maps_to_robot_left_leg():
    """Person raises their right knee: thigh 30° forward, shank vertical.
    Mirror → robot LEFT leg: hip flexion (negative l_hip_pitch, sim sign)
    and knee bend (positive l_knee). Person's left leg stays neutral."""
    dy = 0.4 * math.cos(math.radians(30))
    dz = -0.4 * math.sin(math.radians(30))  # forward = toward camera = -z
    body = _build_body(
        r_knee=(-0.1, dy, dz),
        r_ankle=(-0.1, dy + 0.4, dz),  # shank straight down from knee
        img_r_knee=(0.45, 0.75),
    )
    targets = compute_joint_targets(body, head_pose=None)

    assert targets["l_hip_pitch"] == pytest.approx(-math.radians(30), abs=1e-3)
    # +30° knee bend is shallower than the hardware range's minimum bend, so
    # it clamps up to the bound.
    assert targets["l_knee"] == pytest.approx(JOINT_LIMITS["l_knee"].clamp(math.radians(30)), abs=1e-3)
    assert targets["l_hip_roll"] == pytest.approx(0.0, abs=1e-3)
    # Person's left leg (robot right) is still standing (0 clamps to the bound)
    assert targets["r_hip_pitch"] == pytest.approx(JOINT_LIMITS["r_hip_pitch"].clamp(0.0), abs=1e-3)
    assert targets["r_knee"] == pytest.approx(JOINT_LIMITS["r_knee"].clamp(0.0), abs=1e-3)


def test_leg_abduction_maps_mirrored():
    """Person swings their right leg 20° out to the side (straight leg).
    Mirror → robot LEFT leg abducts: negative l_hip_roll (sim sign)."""
    dx = -0.4 * math.sin(math.radians(20))  # person's right = -x
    dy = 0.4 * math.cos(math.radians(20))
    body = _build_body(
        r_knee=(-0.1 + dx, dy, 0.0),
        r_ankle=(-0.1 + 2 * dx, 2 * dy, 0.0),  # ankle collinear (straight leg)
        img_r_knee=(0.38, 0.76),
        img_r_ankle=(0.31, 0.88),
    )
    targets = compute_joint_targets(body, head_pose=None)

    assert targets["l_hip_roll"] == pytest.approx(-math.radians(20), abs=1e-3)
    assert targets["l_hip_pitch"] == pytest.approx(JOINT_LIMITS["l_hip_pitch"].clamp(0.0), abs=1e-3)
    assert targets["l_knee"] == pytest.approx(JOINT_LIMITS["l_knee"].clamp(0.0), abs=1e-3)
    assert targets["r_hip_roll"] == pytest.approx(0.0, abs=1e-3)


def test_leg_targets_clamped_to_limits():
    """Hip flexion beyond the hardware-derived cap clamps instead of passing
    through: -80° = -1.396 rad exceeds l_hip_pitch's derived minimum."""
    dy = 0.4 * math.cos(math.radians(80))
    dz = -0.4 * math.sin(math.radians(80))  # thigh 80° forward
    body = _build_body(
        r_knee=(-0.1, dy, dz),
        r_ankle=(-0.1, dy + 0.4, dz),
        img_r_knee=(0.45, 0.72),
    )
    targets = compute_joint_targets(body, head_pose=None)
    assert math.radians(-80) < JOINT_LIMITS["l_hip_pitch"].min  # premise: cap is tighter
    assert targets["l_hip_pitch"] == pytest.approx(JOINT_LIMITS["l_hip_pitch"].min, abs=1e-6)


def test_leg_depth_gate_suppresses_leg():
    """Thigh points straight at the camera → hip→knee image projection short →
    that leg's targets are NOT emitted; the other leg is unaffected."""
    body = _build_body(
        r_knee=(-0.1, 0.05, -0.39),        # thigh almost along optical axis
        r_ankle=(-0.1, 0.45, -0.39),
        img_r_knee=(0.452, 0.66),          # < 0.05 of frame from hip image
    )
    targets = compute_joint_targets(body, head_pose=None)
    assert "l_hip_pitch" not in targets
    assert "l_knee" not in targets
    assert "r_hip_pitch" in targets  # person's left leg still tracked


def test_hidden_knee_snaps_both_legs_to_stand():
    """Either knee below the 0.6 knee gate → BOTH legs snap to the stand pose.
    Leg retargeting requires both knees clearly visible; a single hidden knee
    straightens the whole lower body rather than holding a stale/bent pose."""
    body = _build_body()
    body[26]["visibility"] = 0.1  # person's right knee hidden
    targets = compute_joint_targets(body, head_pose=None)
    # Legs present, and set to the stand-keyframe values (not retargeted).
    assert targets["l_hip_pitch"] == pytest.approx(HW_STAND_RAD["l_hip_pitch"])
    assert targets["r_hip_pitch"] == pytest.approx(HW_STAND_RAD["r_hip_pitch"])
    assert targets["l_knee"] == pytest.approx(HW_STAND_RAD["l_knee"])
    assert targets["r_knee"] == pytest.approx(HW_STAND_RAD["r_knee"])
    assert targets["l_hip_roll"] == pytest.approx(0.0)
    assert targets["r_hip_roll"] == pytest.approx(0.0)


def test_knee_below_knee_gate_but_above_default_stands_legs():
    """A knee at 0.55 clears the old 0.5 default but not the stricter 0.6 knee
    gate → legs snap to stand. Guards the knee-specific threshold specifically."""
    body = _build_body()
    body[26]["visibility"] = 0.55
    targets = compute_joint_targets(body, head_pose=None)
    assert targets["l_hip_pitch"] == pytest.approx(HW_STAND_RAD["l_hip_pitch"])
    assert targets["r_knee"] == pytest.approx(HW_STAND_RAD["r_knee"])


def test_hidden_ankle_skips_knee_only():
    """Ankle invisible (cut off at frame bottom) → hip pitch/roll still
    emitted, knee bend omitted."""
    body = _build_body()
    body[28]["visibility"] = 0.1  # person's right ankle hidden
    targets = compute_joint_targets(body, head_pose=None)
    assert "l_hip_pitch" in targets
    assert "l_hip_roll" in targets
    assert "l_knee" not in targets


def test_hidden_hips_stand_legs():
    """A hip below the visibility gate → no pelvis frame → legs snap to stand.

    (In the live flow vision_server's hips_detected gate returns pose_detected
    False before this is reached; calling compute_joint_targets directly here
    exercises the degenerate-pelvis branch, which stands the legs.)"""
    body = _build_body()
    body[24]["visibility"] = 0.1
    targets = compute_joint_targets(body, head_pose=None)
    assert targets["l_hip_pitch"] == pytest.approx(HW_STAND_RAD["l_hip_pitch"])
    assert targets["r_hip_pitch"] == pytest.approx(HW_STAND_RAD["r_hip_pitch"])
    assert targets["l_knee"] == pytest.approx(HW_STAND_RAD["l_knee"])
    assert targets["r_knee"] == pytest.approx(HW_STAND_RAD["r_knee"])
