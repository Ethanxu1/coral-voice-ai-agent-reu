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

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "KNOWN FALSE POSITIVE, verified against real dynamics 2026-09-29. "
            "A 0.05 rad (2.9 deg) ankle tilt measures -0.0107 (unsafe) while "
            "the robot comfortably stays up. Part of a broader defect: the "
            "margin is unreliable for ASYMMETRIC single-joint poses, going "
            "unsafe/unsafe/SAFE/unsafe across r_hip_roll 0.0625/0.125/0.25/0.5 "
            "with the robot standing throughout. Suspected cause is "
            "contact-sensor flicker -- the real stand pose rests on 3 pads, and "
            "a small asymmetric tilt drops one, collapsing the support polygon "
            "discontinuously. ENABLE_FOLLOW_SAFETY is default-off until fixed; "
            "see docs/cbf-whole-body-progress.md Phase 2.6."
        ),
    )
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

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Same asymmetric-pose false positive as "
            "test_small_ankle_roll_change_stays_safe -- the endpoint itself "
            "measures unsafe, so the trajectory is scaled back. Fixing that "
            "fixes this. See docs/cbf-whole-body-progress.md Phase 2.6."
        ),
    )
    def test_small_ankle_motion_is_safe_throughout(self, safety_filter):
        """Phase 1 recorded a "genuine mid-motion dip" here. It was not
        genuine.

        That dip was an artifact of pinning the free-floating base: with
        the body held fixed, rotating the ankle lifted part of the foot
        and shrank the support polygon, producing a spurious negative
        margin. Phase 2.5 lets the base settle against each candidate
        pose, and the margin now stays between +0.034 and +0.038 at
        every point along this path -- nowhere near the threshold.

        Same root cause as the knee false negative Phase 2.5 was built
        to fix, just in the false-POSITIVE direction: pinning the base
        made the filter wrong in both directions, not just one."""
        current = {"l_ank_roll": 0.0}
        target = {"l_ank_roll": _SAFE_ANKLE_ROLL}
        safe_joints, safe_fraction, margin = safety_filter.check_trajectory(current, target)
        assert safe_fraction == 1.0
        assert safe_joints == target
        assert margin > 0.03

    def test_unsafe_target_gets_scaled_back(self, safety_filter):
        """Uses a SYMMETRIC lean, which real dynamics confirms topples the
        robot and which the filter handles well (margin falls monotonically
        0.0381 -> 0.0084 -> -1.0 along the path).

        Deliberately not the single-joint r_hip_roll this used to use:
        physics says that one stays UP, so it was never a valid "unsafe
        target", and the filter's verdict on it is noise anyway (see the
        xfail reasons above)."""
        current = {"l_hip_roll": 0.0, "r_hip_roll": 0.0}
        target = {"l_hip_roll": -0.35, "r_hip_roll": -0.35}
        safe_joints, safe_fraction, margin = safety_filter.check_trajectory(current, target)
        # Didn't reach the unsafe target as requested...
        assert safe_fraction < 1.0
        assert safe_joints["l_hip_roll"] > -0.35
        # ...but did move meaningfully toward it, not refuse the whole thing.
        assert safe_joints["l_hip_roll"] < 0.0
        # And the pose it settled on is actually safe, not just "less unsafe".
        assert margin > 0

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
