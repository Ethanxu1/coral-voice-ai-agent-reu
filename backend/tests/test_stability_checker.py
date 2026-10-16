"""Tests for the dynamics fall checker (StabilityChecker)."""

import pytest

from app.collision.stability_checker import StabilityChecker


# Two saved poses captured from a real 2026-08-31 demo session (see
# .agents/fixes/2026-08-31-stability-checker-step-input-false-fall.md). Both
# are individually stable — the robot held each of them — but the transition
# between them used to be flagged as a fall because the checker applied the
# target as an instantaneous step, and the violent full-body swing toppled the
# model. Real dispatches slew servos over ~1s, so the checker must pace the
# transition the same way.
POSE_KEEP_THOSE = {
    "l_ank_roll": 0.0, "r_ank_roll": -0.0698,
    "l_ank_pitch": 0.4538, "r_ank_pitch": -0.4538,
    "l_knee": 0.925, "r_knee": -0.925,
    "l_hip_pitch": -0.4887, "r_hip_pitch": 0.4887,
    "l_hip_roll": 0.0, "r_hip_roll": 0.0,
    "l_hip_yaw": 0.0, "r_hip_yaw": 0.0,
    "l_sho_pitch": 1.184761809252333, "r_sho_pitch": 0.8496585928694219,
    "l_sho_roll": 0.20939632679489661, "r_sho_roll": -0.20939632679489661,
    "l_el_pitch": -0.6408849013323178, "r_el_pitch": -0.7539822368615503,
    "l_el_yaw": -3.673205103416066e-06, "r_el_yaw": 3.673205103416066e-06,
    "l_gripper": 0.0, "r_gripper": 0.0,
    "head_pan": 0.0, "head_tilt": 0.0,
}

POSE_THUMBS_UP = {
    "l_ank_roll": 0.0, "r_ank_roll": -0.0698,
    "l_ank_pitch": 0.4538, "r_ank_pitch": -0.4538,
    "l_knee": 0.925, "r_knee": -0.925,
    "l_hip_pitch": -0.4887, "r_hip_pitch": 0.4887,
    "l_hip_roll": 0.0, "r_hip_roll": 0.0,
    "l_hip_yaw": 0.0, "r_hip_yaw": 0.0,
    "l_sho_pitch": 1.9638767873426017, "r_sho_pitch": 1.7753812281272143,
    "l_sho_roll": -0.7582142105107597, "r_sho_roll": 0.4566213157661395,
    "l_el_pitch": -0.55710909723659, "r_el_pitch": -0.7539822368615503,
    "l_el_yaw": -0.992746951739478, "r_el_yaw": 1.3069062170984573,
    "l_gripper": 0.0, "r_gripper": 0.0,
    "head_pan": -0.1256637061435917, "head_tilt": 0.1801179788058148,
}


@pytest.fixture(scope="module")
def checker() -> StabilityChecker:
    return StabilityChecker()


def test_transition_between_two_stable_poses_is_not_a_fall(checker):
    """Regression: replaying "Thumbs up." from the "Keep those." pose must not
    be blocked as a fall risk — both poses are stable, and the paced real
    servos ride the transition without toppling."""
    result = checker.check_fall(POSE_THUMBS_UP, current_joints=POSE_KEEP_THOSE)
    assert not result["fell"], (
        f"stable->stable transition flagged as fall: head_z={result['head_z']} "
        f"< threshold {result['threshold_z']}"
    )


def test_genuinely_unstable_lean_is_still_flagged(checker):
    """Guard: pacing the transition must not mask real topples. A hard forward
    hip lean with no knee/ankle compensation puts the COM past the toes."""
    lean = {"l_hip_pitch": 1.0, "r_hip_pitch": -1.0}
    result = checker.check_fall(lean)
    assert result["fell"], (
        f"expected the lean to be flagged as a fall, got head_z={result['head_z']}"
    )


def test_live_balance_snapshot_is_used_as_the_shadow_start(checker):
    upright = checker.check_fall({}, transition_seconds=0.22)
    fallen_qpos = checker.data.qpos.copy()
    fallen_qvel = checker.data.qvel.copy()
    fallen_ctrl = checker.data.ctrl.copy()
    fallen_qpos[2] = 0.05

    result = checker.check_fall(
        {},
        transition_seconds=0.22,
        dynamics_state={
            "qpos": fallen_qpos.tolist(),
            "qvel": fallen_qvel.tolist(),
            "ctrl": fallen_ctrl.tolist(),
        },
    )

    assert not upright["fell"]
    assert result["fell"]


def test_live_snapshot_keeps_omitted_joints_at_their_current_targets(checker):
    """The shadow move must match /move: omitted joints do not move."""
    checker.check_fall({}, transition_seconds=0.22)
    qpos = checker.data.qpos.copy()
    qvel = checker.data.qvel.copy()
    ctrl = checker.data.ctrl.copy()
    omitted_joint = "l_sho_pitch"
    omitted_addr = checker._qpos_addr[omitted_joint]
    omitted_actuator = checker._actuator_id[omitted_joint]
    physical_position = float(qpos[omitted_addr]) + 0.15
    current_target = physical_position + 0.35
    qpos[omitted_addr] = physical_position
    ctrl[omitted_actuator] = current_target

    checker._settle(
        {"head_pan": 0.1},
        transition_seconds=0.22,
        dynamics_state={
            "qpos": qpos.tolist(),
            "qvel": qvel.tolist(),
            "ctrl": ctrl.tolist(),
        },
    )

    assert checker.data.ctrl[omitted_actuator] == pytest.approx(current_target)
