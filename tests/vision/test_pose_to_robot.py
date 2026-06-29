"""End-to-end tests for compute_joint_targets: synthetic landmarks → joint dict.

Verifies the full pipeline (depth gate + visibility check + rotation extraction
+ mirror mode + STAND offset + clamping) produces sensible servo targets for
canonical poses.
"""

from __future__ import annotations

import math

import pytest

from coral_agent.vision.pose_to_robot import (
    _STAND_L_SHO_ROLL,
    _STAND_R_SHO_ROLL,
    compute_joint_targets,
)


def _empty_landmark() -> dict:
    return {"x": 0.5, "y": 0.5, "z": 0.0, "visibility": 0.0,
            "xw": 0.0, "yw": 0.0, "zw": 0.0}


def _build_body(
    *,
    l_sho=(+0.2, 0.5, 0.0),
    r_sho=(-0.2, 0.5, 0.0),
    l_hip=(+0.1, 0.0, 0.0),
    r_hip=(-0.1, 0.0, 0.0),
    l_elbow=(+0.2, 0.2, 0.0),  # default = arms-down rest (elbow below shoulder)
    r_elbow=(-0.2, 0.2, 0.0),
    l_wrist=(+0.2, -0.1, 0.0),
    r_wrist=(-0.2, -0.1, 0.0),
    l_pinky=None,
    r_pinky=None,
    l_index=None,
    r_index=None,
    img_l_sho=(0.62, 0.40),
    img_r_sho=(0.38, 0.40),
    img_l_elbow=(0.75, 0.55),
    img_r_elbow=(0.25, 0.55),
    img_l_wrist=(0.85, 0.65),
    img_r_wrist=(0.15, 0.65),
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
    # nose + ears so any head consumer doesn't crash
    set_pt(0, (0.0, 0.7, 0.1), (0.5, 0.30))
    set_pt(7, (+0.08, 0.65, 0.0), (0.56, 0.32))
    set_pt(8, (-0.08, 0.65, 0.0), (0.44, 0.32))
    return body


def test_t_pose_targets():
    """Both arms abducted to T → l_sho_roll and r_sho_roll both move from
    STAND offset toward 0 by ~π/2; pitches near 0."""
    body = _build_body(
        l_elbow=(+0.5, 0.5, 0.0),
        r_elbow=(-0.5, 0.5, 0.0),
        l_wrist=(+0.8, 0.5, 0.0),
        r_wrist=(-0.8, 0.5, 0.0),
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

    # Elbows extended → bend≈0
    assert abs(targets["l_el_yaw"]) < 1e-3
    assert abs(targets["r_el_yaw"]) < 1e-3


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
        l_elbow=(+0.2, 0.5, 0.3),  # 0.3m forward from shoulder
        r_elbow=(-0.2, 0.5, 0.3),
        l_wrist=(+0.2, 0.5, 0.6),
        r_wrist=(-0.2, 0.5, 0.6),
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
    """Either shoulder hidden → torso frame unbuildable → both arms suppressed."""
    body = _build_body()
    body[12]["visibility"] = 0.1
    targets = compute_joint_targets(body, head_pose=None)
    assert "l_sho_pitch" not in targets
    assert "r_sho_pitch" not in targets


def test_forearm_twist_emits_el_pitch_when_hand_landmarks_present():
    """Both arms in T-pose with palm-down hands → l_el_pitch / r_el_pitch
    are emitted and finite (sign is convention-defined; here we just verify
    the joints make it through the pipeline with hand landmarks)."""
    body = _build_body(
        l_elbow=(+0.5, 0.5, 0.0),
        r_elbow=(-0.5, 0.5, 0.0),
        l_wrist=(+0.8, 0.5, 0.0),
        r_wrist=(-0.8, 0.5, 0.0),
        l_pinky=(+0.8, 0.5, -0.05),
        r_pinky=(-0.8, 0.5, -0.05),
        l_index=(+0.8, 0.5, +0.05),
        r_index=(-0.8, 0.5, +0.05),
        img_l_elbow=(0.85, 0.40),
        img_r_elbow=(0.15, 0.40),
        img_l_wrist=(0.98, 0.40),
        img_r_wrist=(0.02, 0.40),
    )
    targets = compute_joint_targets(body, head_pose=None)
    assert "l_el_pitch" in targets
    assert "r_el_pitch" in targets
    # Palm-down should produce the same anatomical twist on both sides
    assert targets["l_el_pitch"] == pytest.approx(targets["r_el_pitch"], abs=1e-3)


def test_forearm_twist_omitted_when_hand_landmarks_missing():
    """Hand landmarks invisible (visibility=0 by default) → twist omitted,
    rest of the arm targets still emitted."""
    body = _build_body(
        l_elbow=(+0.5, 0.5, 0.0),
        r_elbow=(-0.5, 0.5, 0.0),
        l_wrist=(+0.8, 0.5, 0.0),
        r_wrist=(-0.8, 0.5, 0.0),
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
