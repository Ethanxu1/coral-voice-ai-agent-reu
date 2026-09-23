"""Tests for the CBF-style safety filter (backend/app/balance/safety_filter.py).

Uses the real AiNex model throughout (matching this project's established
pattern for sim-facing code, no mocking of MuJoCo) — module-scoped since
SafetyFilter.__init__ does a real ~1.5s physics settle once, and tests
don't mutate any state check_pose/check_trajectory doesn't itself reset
before use.

Real, empirically-found values used below (not guesses): the settled
stand pose has stability_margin ≈ +0.038; a moderate r_hip_roll splay
(0.3 rad) alone drops it to ≈ -0.006 (unsafe) — found by directly
querying SafetyFilter.check_pose across a range of candidate joints
before writing these assertions. An arm movement (l_sho_pitch) was
used for the "safe throughout the whole trajectory" case rather than a
leg/ankle joint — checking the actual per-step margin trace (not
guessed) found that even a small ankle-roll motion has a brief,
genuine mid-motion dip (part of the foot momentarily lifts as the
ankle rotates through), which the filter correctly catches; an arm
movement doesn't touch leg/foot contact geometry at all and reliably
has none.
"""

from __future__ import annotations

import pytest

from app.balance.safety_filter import SafetyFilter

# A hip-roll splay large enough to reliably push the CoM outside the
# support base (found empirically: 0.3 rad already goes negative).
_UNSAFE_HIP_ROLL = 0.5
# A small ankle-only change that stays safe (ankles are low-mass and
# close to the feet -- much less CoM-shifting than a hip movement).
_SAFE_ANKLE_ROLL = 0.05
# An arm movement -- doesn't touch leg/foot contact geometry at all, so
# unlike the ankle case, its whole interpolated path stays safe (see
# module docstring).
_SAFE_ARM_PITCH = 0.5


@pytest.fixture(scope="module")
def safety_filter() -> SafetyFilter:
    return SafetyFilter()


class TestCheckPose:
    def test_unmodified_stand_pose_is_safe(self, safety_filter):
        assert safety_filter.check_pose({}) > 0

    def test_large_hip_roll_splay_is_unsafe(self, safety_filter):
        assert safety_filter.check_pose({"r_hip_roll": _UNSAFE_HIP_ROLL}) < 0

    def test_small_ankle_roll_change_stays_safe(self, safety_filter):
        assert safety_filter.check_pose({"l_ank_roll": _SAFE_ANKLE_ROLL}) > 0


class TestCheckTrajectory:
    def test_no_movement_returns_target_unchanged(self, safety_filter):
        stand = {"l_ank_roll": 0.0}
        safe_joints, safe_fraction, margin = safety_filter.check_trajectory(stand, stand)
        assert safe_joints == stand
        assert safe_fraction == 1.0
        assert margin > 0

    def test_safe_target_passes_through_completely_unchanged(self, safety_filter):
        current = {"l_sho_pitch": 0.0}
        target = {"l_sho_pitch": _SAFE_ARM_PITCH}
        safe_joints, safe_fraction, margin = safety_filter.check_trajectory(current, target)
        assert safe_joints == target
        assert safe_fraction == 1.0
        assert margin > 0

    def test_small_ankle_motion_can_have_a_genuine_mid_motion_dip(self, safety_filter):
        """NOT a bug: checked the actual per-step margin trace directly
        (not guessed) and found part of the foot genuinely, briefly
        lifts partway through this small ankle-roll motion even though
        both the start and end poses are safe on their own -- exactly
        the kind of thing a trajectory-level (not just endpoint) check
        is supposed to catch. Asserts the filter catches it, not that
        the specific fraction is some exact value."""
        current = {"l_ank_roll": 0.0}
        target = {"l_ank_roll": _SAFE_ANKLE_ROLL}
        safe_joints, safe_fraction, margin = safety_filter.check_trajectory(current, target)
        assert safe_fraction < 1.0
        assert margin >= 0
        assert safe_joints["l_ank_roll"] < _SAFE_ANKLE_ROLL

    def test_unsafe_target_gets_scaled_back(self, safety_filter):
        current = {"r_hip_roll": 0.0}
        target = {"r_hip_roll": _UNSAFE_HIP_ROLL}
        safe_joints, safe_fraction, margin = safety_filter.check_trajectory(current, target)
        # Didn't reach the unsafe target as requested...
        assert safe_fraction < 1.0
        assert safe_joints["r_hip_roll"] < _UNSAFE_HIP_ROLL
        # ...but did move meaningfully toward it, not refuse the whole thing.
        assert safe_joints["r_hip_roll"] > 0.0
        # And the pose it settled on is actually safe, not just "less unsafe".
        assert margin >= 0

    def test_scaled_back_result_is_consistent_with_check_pose(self, safety_filter):
        """The margin check_trajectory reports for its own scaled-back
        result should match what check_pose independently computes for
        that same pose — these are two different code paths computing
        the same thing, so this cross-checks they agree."""
        current = {"r_hip_roll": 0.0}
        target = {"r_hip_roll": _UNSAFE_HIP_ROLL}
        safe_joints, _fraction, margin = safety_filter.check_trajectory(current, target)
        assert safety_filter.check_pose(safe_joints) == pytest.approx(margin, abs=1e-6)

    def test_unrelated_joint_in_target_but_not_current_is_treated_as_moving(self, safety_filter):
        """A joint present in target_joints but absent from current_joints
        is treated as moving from its target value (i.e. not moving) --
        matching CollisionChecker.check_trajectory's own documented
        convention for the same situation."""
        current: dict[str, float] = {}
        target = {"l_ank_roll": _SAFE_ANKLE_ROLL}
        safe_joints, safe_fraction, _margin = safety_filter.check_trajectory(current, target)
        assert safe_fraction == 1.0
        assert safe_joints == target
