"""Regression tests for torso-relative joint-angle extraction.

The bug these tests guard against: the previous shoulder pitch/roll math (using
MediaPipe's non-metric image z) coupled the two axes so that arms-forward and
arms-side were not separable. After switching to `pose_world_landmarks` plus
rotation-matrix decomposition, pitch must be independent of roll abduction.

Synthetic world frame used in this file:
  +x = person's left (anatomical)
  +y = up
  +z = forward (out of chest, toward camera)
Hips at y=0, shoulders at y≈0.5. This is self-consistent; the geometry helpers
derive the torso frame from the landmarks themselves, so absolute axis choice is
not load-bearing.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from coral_agent.vision import geometry


# ── Canonical landmark positions ───────────────────────────────────────────────

L_SHO = np.array([+0.2, 0.5, 0.0])
R_SHO = np.array([-0.2, 0.5, 0.0])
L_HIP = np.array([+0.1, 0.0, 0.0])
R_HIP = np.array([-0.1, 0.0, 0.0])


@pytest.fixture
def R_torso():
    return geometry.torso_frame(L_SHO, R_SHO, L_HIP, R_HIP)


def test_torso_frame_is_identity_for_upright_neutral(R_torso):
    """Upright torso with shoulders along x and hips below should yield identity."""
    np.testing.assert_allclose(R_torso, np.eye(3), atol=1e-6)


# ── 4-pose battery ─────────────────────────────────────────────────────────────


def test_t_pose_left_arm(R_torso):
    """Arms straight out to the sides: pitch=0, roll_abd=π/2."""
    elbow = np.array([+0.5, 0.5, 0.0])  # 0.3m to person's left of shoulder
    pitch, roll_abd = geometry.shoulder_pitch_roll(L_SHO, elbow, R_torso, side="left")
    assert pitch == pytest.approx(0.0, abs=1e-6)
    assert roll_abd == pytest.approx(math.pi / 2, abs=1e-6)


def test_t_pose_right_arm(R_torso):
    """Right arm mirror of left: still pitch=0, roll_abd=π/2 (magnitudes)."""
    elbow = np.array([-0.5, 0.5, 0.0])
    pitch, roll_abd = geometry.shoulder_pitch_roll(R_SHO, elbow, R_torso, side="right")
    assert pitch == pytest.approx(0.0, abs=1e-6)
    assert roll_abd == pytest.approx(math.pi / 2, abs=1e-6)


def test_arms_forward_left(R_torso):
    """Arm pointing straight forward: pitch=π/2, roll_abd=0."""
    elbow = L_SHO + np.array([0.0, 0.0, 0.3])
    pitch, roll_abd = geometry.shoulder_pitch_roll(L_SHO, elbow, R_torso, side="left")
    assert pitch == pytest.approx(math.pi / 2, abs=1e-6)
    assert roll_abd == pytest.approx(0.0, abs=1e-6)


def test_arms_overhead_left(R_torso):
    """Arm pointing straight up: pitch=π, roll_abd=0."""
    elbow = L_SHO + np.array([0.0, 0.3, 0.0])
    pitch, roll_abd = geometry.shoulder_pitch_roll(L_SHO, elbow, R_torso, side="left")
    assert pitch == pytest.approx(math.pi, abs=1e-6)
    assert roll_abd == pytest.approx(0.0, abs=1e-6)


def test_arms_down_left(R_torso):
    """Arm hanging at side: pitch=0, roll_abd=0."""
    elbow = L_SHO + np.array([0.0, -0.3, 0.0])
    pitch, roll_abd = geometry.shoulder_pitch_roll(L_SHO, elbow, R_torso, side="left")
    assert pitch == pytest.approx(0.0, abs=1e-6)
    assert roll_abd == pytest.approx(0.0, abs=1e-6)


# ── Decoupling: the bug fix ────────────────────────────────────────────────────


def test_pitch_invariant_under_roll(R_torso):
    """T-pose and arms-down both have pitch=0 even though their roll differs.

    This is the original-bug failure mode: the old `atan2(-dz, dy)` math with
    image-space z couldn't separate forward flexion from abduction.
    """
    t_pose_elbow = np.array([+0.5, 0.5, 0.0])
    rest_elbow = L_SHO + np.array([0.0, -0.3, 0.0])

    pitch_t, roll_t = geometry.shoulder_pitch_roll(L_SHO, t_pose_elbow, R_torso, side="left")
    pitch_r, roll_r = geometry.shoulder_pitch_roll(L_SHO, rest_elbow, R_torso, side="left")

    assert pitch_t == pytest.approx(pitch_r, abs=1e-6)
    assert roll_t > 1.0  # T-pose is abducted
    assert roll_r == pytest.approx(0.0, abs=1e-6)


def test_roll_invariant_under_pitch(R_torso):
    """Arms-forward and arms-down have the same roll_abd=0 despite different pitch."""
    fwd_elbow = L_SHO + np.array([0.0, 0.0, 0.3])
    down_elbow = L_SHO + np.array([0.0, -0.3, 0.0])

    _, roll_fwd = geometry.shoulder_pitch_roll(L_SHO, fwd_elbow, R_torso, side="left")
    _, roll_down = geometry.shoulder_pitch_roll(L_SHO, down_elbow, R_torso, side="left")

    assert roll_fwd == pytest.approx(roll_down, abs=1e-6)


# ── Elbow ──────────────────────────────────────────────────────────────────────


def test_elbow_fully_extended():
    """Straight arm → bend=0."""
    shoulder = np.array([0.0, 0.5, 0.0])
    elbow = np.array([0.3, 0.5, 0.0])
    wrist = np.array([0.6, 0.5, 0.0])
    assert geometry.elbow_bend(shoulder, elbow, wrist) == pytest.approx(0.0, abs=1e-6)


def test_elbow_right_angle():
    """Forearm perpendicular to upper arm → bend=π/2."""
    shoulder = np.array([0.0, 0.5, 0.0])
    elbow = np.array([0.3, 0.5, 0.0])
    wrist = np.array([0.3, 0.5, 0.3])  # forearm goes forward
    assert geometry.elbow_bend(shoulder, elbow, wrist) == pytest.approx(math.pi / 2, abs=1e-6)


# ── Head pose decoupling ───────────────────────────────────────────────────────


def test_head_pan_zero_when_looking_forward(R_torso):
    """Head looking straight forward → pan=0, tilt=0."""
    nose = np.array([0.0, 0.7, 0.1])  # nose just forward of mid-shoulder
    l_ear = np.array([+0.08, 0.7, 0.0])
    r_ear = np.array([-0.08, 0.7, 0.0])
    pan, tilt, roll = geometry.head_pan_tilt_roll(nose, l_ear, r_ear, R_torso)
    assert pan == pytest.approx(0.0, abs=1e-6)
    assert tilt == pytest.approx(0.0, abs=1e-6)
    assert roll == pytest.approx(0.0, abs=1e-6)


def test_head_pan_decoupled_from_torso_rotation():
    """Person's torso rotated 30° to the side; head still faces forward in the
    world → head_pan should be ~30° (i.e., turned relative to torso), NOT 0.

    Conversely: torso fixed forward + head turned to person's right → pan > 0.

    This guards against the old solvePnP head pose mixing torso rotation into
    head_pan.
    """
    # Build a torso rotated 30° (yaw) about world Y.
    yaw = math.radians(30)
    Rz = np.array([
        [math.cos(yaw),  0, math.sin(yaw)],
        [0,              1, 0           ],
        [-math.sin(yaw), 0, math.cos(yaw)],
    ])

    def rot(p):
        return Rz @ p

    R_t = geometry.torso_frame(rot(L_SHO), rot(R_SHO), rot(L_HIP), rot(R_HIP))

    # Head still faces world-forward (+z), not torso-forward.
    nose = np.array([0.0, 0.7, 0.1])
    l_ear = np.array([+0.08, 0.7, 0.0])
    r_ear = np.array([-0.08, 0.7, 0.0])
    pan, _, _ = geometry.head_pan_tilt_roll(nose, l_ear, r_ear, R_t)

    # Head is turned 30° relative to the now-rotated torso.
    assert abs(abs(pan) - yaw) < math.radians(2)


def test_head_pan_sign_convention(R_torso):
    """Head turned toward person's right → positive pan
    (matches validation.py's 'head right = positive head_pan').
    """
    # Person's right is -x_torso → head nose pointing to (-x, +z direction).
    nose = np.array([-0.05, 0.7, 0.1])
    l_ear = np.array([+0.06, 0.7, 0.03])
    r_ear = np.array([-0.10, 0.7, -0.03])
    pan, _, _ = geometry.head_pan_tilt_roll(nose, l_ear, r_ear, R_torso)
    assert pan > 0


# ── Forearm twist ──────────────────────────────────────────────────────────────


def test_forearm_twist_returns_none_for_zero_forearm(R_torso):
    """Wrist coincident with elbow → degenerate, returns None."""
    p = np.array([0.0, 0.5, 0.0])
    assert (
        geometry.forearm_twist(p, p, p + np.array([0.01, 0, 0]), p + np.array([-0.01, 0, 0]), R_torso, side="left")
        is None
    )


def test_forearm_twist_returns_none_for_zero_palm(R_torso):
    """Index and pinky coincident → degenerate, returns None."""
    elbow = np.array([0.3, 0.5, 0.0])
    wrist = np.array([0.6, 0.5, 0.0])
    p = wrist + np.array([0.0, 0.0, 0.05])
    assert geometry.forearm_twist(elbow, wrist, p, p, R_torso, side="left") is None


def test_forearm_twist_t_pose_palm_down_left(R_torso):
    """Left arm in T-pose, palm facing down: palm-across (pinky→index) points
    forward; with torso-up as reference (perp to forearm) it should be ~-π/2.

    Torso-up = +y; forearm = +x (left arm extended). Pinky→index = +z (forward).
    The angle from +y to +z about +x is +π/2; with the sign convention "right
    arm is mirrored", left arm sees no flip, so result is +π/2.
    """
    elbow = np.array([+0.5, 0.5, 0.0])
    wrist = np.array([+0.8, 0.5, 0.0])
    # Hand at the wrist with knuckles forward (palm facing down)
    index = wrist + np.array([0.0, 0.0, +0.05])
    pinky = wrist + np.array([0.0, 0.0, -0.05])
    twist = geometry.forearm_twist(elbow, wrist, index, pinky, R_torso, side="left")
    assert twist is not None
    assert twist == pytest.approx(math.pi / 2, abs=1e-6)


def test_forearm_twist_t_pose_palm_forward_left(R_torso):
    """Left arm in T-pose, palm facing forward: palm-across points up → twist ~0."""
    elbow = np.array([+0.5, 0.5, 0.0])
    wrist = np.array([+0.8, 0.5, 0.0])
    index = wrist + np.array([0.0, +0.05, 0.0])
    pinky = wrist + np.array([0.0, -0.05, 0.0])
    twist = geometry.forearm_twist(elbow, wrist, index, pinky, R_torso, side="left")
    assert twist is not None
    assert twist == pytest.approx(0.0, abs=1e-6)


def test_forearm_twist_anatomical_sign_matches_across_arms(R_torso):
    """Same anatomical hand pose on both arms (palm-down T-pose) should produce
    the same signed twist — that's what the per-side mirror parameter is for."""
    # Left arm palm-down
    elbow_l = np.array([+0.5, 0.5, 0.0])
    wrist_l = np.array([+0.8, 0.5, 0.0])
    index_l = wrist_l + np.array([0.0, 0.0, +0.05])
    pinky_l = wrist_l + np.array([0.0, 0.0, -0.05])
    twist_l = geometry.forearm_twist(elbow_l, wrist_l, index_l, pinky_l, R_torso, side="left")

    # Right arm palm-down (mirror of left)
    elbow_r = np.array([-0.5, 0.5, 0.0])
    wrist_r = np.array([-0.8, 0.5, 0.0])
    index_r = wrist_r + np.array([0.0, 0.0, +0.05])
    pinky_r = wrist_r + np.array([0.0, 0.0, -0.05])
    twist_r = geometry.forearm_twist(elbow_r, wrist_r, index_r, pinky_r, R_torso, side="right")

    assert twist_l is not None and twist_r is not None
    assert twist_l == pytest.approx(twist_r, abs=1e-6)


# ── Depth-ambiguity gate ───────────────────────────────────────────────────────


def test_depth_gate_triggers_for_arm_along_optical_axis():
    """Shoulder and elbow at nearly the same image position → gate triggers."""
    sh = np.array([0.5, 0.5])
    el = np.array([0.51, 0.51])  # ~0.014 distance, below 0.05 threshold
    assert geometry.arm_image_projection_short(sh, el, threshold=0.05) is True


def test_depth_gate_clear_for_lateral_arm():
    """Arm spread across the frame → gate clear."""
    sh = np.array([0.4, 0.4])
    el = np.array([0.6, 0.4])  # 0.2 distance
    assert geometry.arm_image_projection_short(sh, el, threshold=0.05) is False
