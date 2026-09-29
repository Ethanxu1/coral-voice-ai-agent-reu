"""The leg-mimicry travel limit (docs/cbf-whole-body-progress.md Phase 2.7).

A full retargeted leg lift topples this robot. `limit_leg_travel` caps
each leg joint to a fraction of its available travel from the stand
pose, so the robot lifts its leg as far as it can while staying up.

A LIMIT, not a scale: gentle leg movements pass through at full
fidelity and only large ones are cut back. The first version scaled
everything proportionally, which shrank small movements too for no
safety benefit.

Sizing is measured, not chosen. Holding a maximum lift for 5s from the
corrected stand stance: 0.1 and 0.2 of available travel stay standing
(0.2 already rolls to -16°, visibly struggling), 0.3 and above topple.
With the limit in place every lift from 5% to 100% of what a person can
do now stays up, clamping at 0.126 rad and a -6.9° lean.
"""

from __future__ import annotations

import pytest

from app import config
from app.validation import JOINT_LIMITS
from app.vision.pose_to_robot import (
    _STAND_LEG_TARGETS,
    limit_leg_travel,
    retarget_neutral_leg_targets,
)

LIMIT = config.LEG_MIMICRY_MAX_TRAVEL


def _reach(joint: str, upward: bool) -> float:
    stand = _STAND_LEG_TARGETS[joint]
    lim = JOINT_LIMITS[joint]
    return (lim.max - stand) if upward else (stand - lim.min)


class TestLimiting:
    def test_a_large_movement_is_cut_back_to_the_limit(self):
        joint = "l_knee"
        stand = _STAND_LEG_TARGETS[joint]
        out = limit_leg_travel({joint: JOINT_LIMITS[joint].max}, 0.15)
        assert out[joint] == pytest.approx(stand + 0.15 * _reach(joint, True))

    def test_a_small_movement_passes_through_untouched(self):
        """The whole point of a limit over a scale — gentle leg movements
        keep full mimicry fidelity."""
        joint = "l_knee"
        target = _STAND_LEG_TARGETS[joint] + 0.05 * _reach(joint, True)
        out = limit_leg_travel({joint: target}, 0.15)
        assert out[joint] == pytest.approx(target)

    def test_limits_both_directions(self):
        joint = "l_hip_pitch"
        stand = _STAND_LEG_TARGETS[joint]
        up = limit_leg_travel({joint: JOINT_LIMITS[joint].max}, 0.15)
        down = limit_leg_travel({joint: JOINT_LIMITS[joint].min}, 0.15)
        assert up[joint] == pytest.approx(stand + 0.15 * _reach(joint, True))
        assert down[joint] == pytest.approx(stand - 0.15 * _reach(joint, False))

    def test_direction_is_preserved(self):
        """Limiting must never flip a movement — the robot should do less
        of what the person did, not the opposite."""
        joint = "l_hip_pitch"
        stand = _STAND_LEG_TARGETS[joint]
        for target in (JOINT_LIMITS[joint].max, JOINT_LIMITS[joint].min):
            out = limit_leg_travel({joint: target}, 0.15)
            assert (out[joint] - stand) * (target - stand) > 0

    def test_fraction_of_one_disables_the_limit(self):
        original = {"l_knee": JOINT_LIMITS["l_knee"].max, "l_sho_pitch": 0.5}
        assert limit_leg_travel(dict(original), 1.0) == original


class TestNeutralIsTheStandPose:
    def test_a_standing_person_maps_to_the_robots_stand_pose(self):
        """Regression guard. Leg angles used to be measured from 0 rad
        clamped into range, putting a motionless person's robot 0.42 rad
        off its own keyframe — 8.7° pitched back rather than +2.7°, and
        lurching whenever the knee-visibility fallback kicked in. Every
        leg lift then started from an already-tipped stance."""
        assert retarget_neutral_leg_targets() == _STAND_LEG_TARGETS

    def test_a_motionless_person_is_left_alone(self):
        out = limit_leg_travel(dict(_STAND_LEG_TARGETS), LIMIT)
        for joint, value in _STAND_LEG_TARGETS.items():
            assert out[joint] == pytest.approx(value), joint


class TestOnlyLegsAreLimited:
    def test_arms_and_head_pass_through_untouched(self):
        """Arms barely shift this robot's CoM (margin holds at ~0.038
        through overhead poses), so limiting them would cost mimicry
        fidelity for no safety gain."""
        targets = {
            "l_sho_pitch": 1.5, "r_sho_roll": -0.9,
            "head_pan": 0.4, "l_el_yaw": -1.2,
            "l_knee": JOINT_LIMITS["l_knee"].max,
        }
        out = limit_leg_travel(dict(targets), 0.15)
        for joint in ("l_sho_pitch", "r_sho_roll", "head_pan", "l_el_yaw"):
            assert out[joint] == targets[joint]
        assert out["l_knee"] != targets["l_knee"]

    def test_absent_leg_joints_are_not_invented(self):
        """compute_joint_targets emits only confidently-tracked joints;
        the limit must not add ones the retargeting chose to omit."""
        out = limit_leg_travel({"l_sho_pitch": 0.3}, 0.15)
        assert set(out) == {"l_sho_pitch"}


class TestConfiguredDefault:
    def test_default_is_inside_the_measured_safe_limit(self):
        """Physics: 0.1 and 0.2 of available travel survive a held
        maximum lift, 0.3 and above topple. 0.2 is already visibly
        struggling, so the default must sit below it."""
        assert 0.0 < LIMIT < 0.2
