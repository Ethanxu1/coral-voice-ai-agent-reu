"""The leg-mimicry cap (docs/cbf-whole-body-progress.md Phase 2.7).

This robot topples at a full retargeted leg lift but stays standing up
to ~70% of one, measured against stepped dynamics. The cap performs
only part of each leg movement, keeping it visible while staying inside
that limit, and halves vision-jitter amplitude in the leg channel.

The reference it scales toward is the RETARGETING'S OWN NEUTRAL (what a
straight leg produces), not the robot's stand keyframe. Those differ by
up to 0.42 rad, so using the keyframe would bend the robot's legs
further the moment a person simply stood still — an offset rather than
a cap. That was a real bug in the first version of this.
"""

from __future__ import annotations

import pytest

from app import config
from app.vision.pose_to_robot import (
    _STAND_LEG_TARGETS,
    retarget_neutral_leg_targets,
    scale_leg_targets_toward_neutral,
)

NEUTRAL = retarget_neutral_leg_targets()


class TestScaling:
    def test_halves_the_distance_from_neutral(self):
        joint = "l_knee"
        target = NEUTRAL[joint] + 1.0
        out = scale_leg_targets_toward_neutral({joint: target}, 0.5)
        assert out[joint] == pytest.approx(NEUTRAL[joint] + 0.5)

    def test_zero_scale_pins_the_legs_to_neutral(self):
        out = scale_leg_targets_toward_neutral({"l_knee": 2.0, "r_hip_pitch": -2.0}, 0.0)
        assert out["l_knee"] == pytest.approx(NEUTRAL["l_knee"])
        assert out["r_hip_pitch"] == pytest.approx(NEUTRAL["r_hip_pitch"])

    def test_scale_of_one_is_a_no_op(self):
        original = {"l_knee": 1.234, "l_sho_pitch": 0.5}
        out = scale_leg_targets_toward_neutral(dict(original), 1.0)
        assert out == original

    def test_direction_is_preserved(self):
        """Capping must never flip a movement's direction — the robot
        should do less of what the person did, not the opposite."""
        joint = "l_hip_pitch"
        base = NEUTRAL[joint]
        for target in (base + 0.8, base - 0.8):
            out = scale_leg_targets_toward_neutral({joint: target}, 0.5)
            assert (out[joint] - base) * (target - base) > 0
            assert abs(out[joint] - base) < abs(target - base)


class TestNeutralReference:
    def test_neutral_is_not_the_stand_keyframe(self):
        """Regression guard for the original bug. These two poses are
        genuinely different, and scaling toward the wrong one silently
        bends the robot's legs while a person stands still."""
        gaps = {j: abs(NEUTRAL[j] - _STAND_LEG_TARGETS[j]) for j in _STAND_LEG_TARGETS}
        assert max(gaps.values()) > 0.4, gaps

    def test_a_standing_person_is_left_alone_by_the_cap(self):
        """The defining property: if the person has not moved their legs,
        capping must change nothing at all, at any scale."""
        for scale in (0.0, 0.25, 0.5, 0.9):
            out = scale_leg_targets_toward_neutral(dict(NEUTRAL), scale)
            for joint, value in NEUTRAL.items():
                assert out[joint] == pytest.approx(value), (joint, scale)


class TestOnlyLegsAreCapped:
    def test_arms_and_head_pass_through_untouched(self):
        """Arms barely shift this robot's CoM (measured: margin holds at
        ~0.038 through even overhead poses), so capping them would cost
        mimicry fidelity for no safety gain."""
        targets = {
            "l_sho_pitch": 1.5, "r_sho_roll": -0.9,
            "head_pan": 0.4, "l_el_yaw": -1.2, "l_knee": 2.0,
        }
        out = scale_leg_targets_toward_neutral(dict(targets), 0.5)
        for joint in ("l_sho_pitch", "r_sho_roll", "head_pan", "l_el_yaw"):
            assert out[joint] == targets[joint]
        assert out["l_knee"] != targets["l_knee"]

    def test_absent_leg_joints_are_not_invented(self):
        """compute_joint_targets emits only confidently-tracked joints;
        the cap must not add ones the retargeting chose to omit."""
        out = scale_leg_targets_toward_neutral({"l_sho_pitch": 0.3}, 0.5)
        assert set(out) == {"l_sho_pitch"}


class TestConfiguredDefault:
    def test_default_is_inside_the_measured_safe_limit(self):
        """Physics puts the fall threshold between 70% and 100% of a full
        lift. Anything at or above that is knowingly unsafe."""
        assert 0.0 < config.LEG_MIMICRY_SCALE <= 0.7
