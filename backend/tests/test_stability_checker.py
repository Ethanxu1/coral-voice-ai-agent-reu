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
