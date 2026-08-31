"""Tests for the deterministic motion fallback planner."""

import math

import pytest

from app.services.motion_fallback import plan_for_description


class TestSingleJointMotions:
    def test_raise_right_arm_forward(self):
        plan = plan_for_description("raise your right arm")
        assert plan is not None
        assert plan.action == "motion"
        assert len(plan.waypoints) == 1
        wp = plan.waypoints[0]
        assert wp.primitives == ["right_arm_forward"]
        assert wp.angle is None  # no explicit angle -> primitive default

    def test_raise_left_arm_with_angle(self):
        plan = plan_for_description("lift your left arm 60 degrees")
        assert plan is not None
        wp = plan.waypoints[0]
        assert wp.primitives == ["left_arm_forward"]
        assert wp.angle == pytest.approx(60.0)

    def test_lower_right_arm_targets_zero(self):
        plan = plan_for_description("lower your right arm")
        assert plan is not None
        wp = plan.waypoints[0]
        assert wp.primitives == ["right_arm_forward"]
        # Lower/drop without an explicit angle should target rest.
        assert wp.angle == pytest.approx(0.0)

    def test_arm_out_right(self):
        plan = plan_for_description("move your right arm out sideways")
        assert plan is not None
        wp = plan.waypoints[0]
        assert wp.primitives == ["right_arm_out"]

    def test_bend_left_elbow(self):
        plan = plan_for_description("bend your left elbow")
        assert plan is not None
        wp = plan.waypoints[0]
        assert wp.primitives == ["left_elbow_bend"]

    def test_straighten_right_elbow_targets_zero(self):
        plan = plan_for_description("straighten your right elbow")
        assert plan is not None
        wp = plan.waypoints[0]
        assert wp.primitives == ["right_elbow_bend"]
        assert wp.angle == pytest.approx(0.0)

    def test_turn_head_left(self):
        plan = plan_for_description("turn your head left")
        assert plan is not None
        wp = plan.waypoints[0]
        assert wp.primitives == ["head_turn"]
        assert wp.direction == "left"

    def test_look_up(self):
        plan = plan_for_description("look up")
        assert plan is not None
        wp = plan.waypoints[0]
        assert wp.primitives == ["head_tilt"]
        assert wp.direction == "up"


class TestBothArms:
    def test_raise_both_arms(self):
        plan = plan_for_description("raise both arms")
        assert plan is not None
        wp = plan.waypoints[0]
        assert set(wp.primitives) == {"left_arm_forward", "right_arm_forward"}

    def test_both_arms_out(self):
        plan = plan_for_description("put both arms out to the side")
        assert plan is not None
        wp = plan.waypoints[0]
        assert set(wp.primitives) == {"left_arm_out", "right_arm_out"}

    def test_lower_both_arms_targets_zero(self):
        plan = plan_for_description("lower both arms")
        assert plan is not None
        wp = plan.waypoints[0]
        assert set(wp.primitives) == {"left_arm_forward", "right_arm_forward"}
        assert wp.angle == pytest.approx(0.0)


class TestChildParaphrases:
    def test_kid_phrase_lift_arm(self):
        plan = plan_for_description("can you lift your right arm")
        assert plan is not None
        assert plan.waypoints[0].primitives == ["right_arm_forward"]

    def test_kid_phrase_drop_arm(self):
        plan = plan_for_description("put down your left arm")
        assert plan is not None
        wp = plan.waypoints[0]
        assert wp.primitives == ["left_arm_forward"]
        assert wp.angle == pytest.approx(0.0)

    def test_kid_phrase_head_look_direction(self):
        plan = plan_for_description("look to the right")
        assert plan is not None
        wp = plan.waypoints[0]
        assert wp.primitives == ["head_turn"]
        assert wp.direction == "right"


class TestCompoundCommands:
    def test_raise_then_lower(self):
        plan = plan_for_description("raise your left arm then lower your right arm")
        assert plan is not None
        assert len(plan.waypoints) == 2
        assert plan.waypoints[0].primitives == ["left_arm_forward"]
        assert plan.waypoints[1].primitives == ["right_arm_forward"]
        assert plan.waypoints[1].angle == pytest.approx(0.0)

    def test_and_then_separator(self):
        plan = plan_for_description("turn your head left and then look up")
        assert plan is not None
        assert len(plan.waypoints) == 2
        assert plan.waypoints[0].primitives == ["head_turn"]
        assert plan.waypoints[0].direction == "left"
        assert plan.waypoints[1].primitives == ["head_tilt"]
        assert plan.waypoints[1].direction == "up"


class TestNoMatch:
    def test_unknown_description_returns_none(self):
        assert plan_for_description("do a backflip") is None

    def test_ambiguous_without_side_returns_none(self):
        # "raise arm" is intentionally not mapped; the LLM or clarification
        # path should handle side ambiguity.
        assert plan_for_description("raise arm") is None
