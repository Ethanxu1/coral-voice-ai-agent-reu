"""Tests for the hybrid regex + LLM intent classifier."""

from app.llm.intent_classifier import (
    HIGH_CONFIDENCE_THRESHOLD,
    classify_intent_regex,
)


class TestImmediateIntents:
    def test_follow_start(self):
        result = classify_intent_regex("follow me")
        assert result is not None
        assert result.type == "immediate"
        assert result.data["intent"] == "follow_start"
        assert result.confidence >= HIGH_CONFIDENCE_THRESHOLD

    def test_follow_stop(self):
        result = classify_intent_regex("stop following")
        assert result is not None
        assert result.data["intent"] == "follow_stop"

    def test_capture(self):
        result = classify_intent_regex("take a snapshot")
        assert result is not None
        assert result.data["intent"] == "capture"

    def test_capture_i_want_phrases(self):
        for phrase in [
            "i want you to take a picture",
            "i want you to capture my pose",
            "i want you to record my pose",
            "record my pose",
            "take a picture of me",
            "picture of me",
            "freeze",
            "lock it in",
        ]:
            result = classify_intent_regex(phrase)
            assert result is not None, phrase
            assert result.data["intent"] == "capture", phrase

    def test_library(self):
        result = classify_intent_regex("my poses")
        assert result is not None
        assert result.data["intent"] == "library"

    def test_exit(self):
        result = classify_intent_regex("goodbye")
        assert result is not None
        assert result.data["intent"] == "exit"

    def test_save_robot_pose(self):
        result = classify_intent_regex("save this pose")
        assert result is not None
        assert result.data["intent"] == "save_robot_pose"

    def test_save_robot_pose_remember_keep(self):
        for phrase in ["remember this", "keep this pose", "save the current pose"]:
            result = classify_intent_regex(phrase)
            assert result is not None, phrase
            assert result.data["intent"] == "save_robot_pose", phrase

    def test_naming(self):
        result = classify_intent_regex("name this pose superhero")
        assert result is not None
        assert result.data["intent"] == "naming"
        assert result.data["name"] == "superhero"


class TestUndoReset:
    def test_undo(self):
        result = classify_intent_regex("undo that")
        assert result is not None
        assert result.data["intent"] == "undo"

    def test_reset(self):
        result = classify_intent_regex("reset")
        assert result is not None
        assert result.data["intent"] == "reset"


class TestMotionIntents:
    def test_head_turn(self):
        result = classify_intent_regex("turn your head left")
        assert result is not None
        assert result.type == "motion"
        assert "left" in result.data["description"].lower()
        assert result.confidence >= HIGH_CONFIDENCE_THRESHOLD

    def test_head_tilt(self):
        result = classify_intent_regex("look up")
        assert result is not None
        assert result.type == "motion"
        assert "up" in result.data["description"].lower()

    def test_raise_arm_explicit_side(self):
        result = classify_intent_regex("raise your right arm forward")
        assert result is not None
        assert result.type == "motion"
        assert "right" in result.data["description"].lower()
        assert result.confidence >= HIGH_CONFIDENCE_THRESHOLD

    def test_raise_arm_ambiguous_side_low_confidence(self):
        result = classify_intent_regex("raise your arm")
        assert result is not None
        assert result.type == "motion"
        # Missing side should drop confidence below the auto-execute threshold.
        assert result.confidence < HIGH_CONFIDENCE_THRESHOLD

    def test_bend_elbow(self):
        result = classify_intent_regex("bend your left elbow")
        assert result is not None
        assert result.type == "motion"
        assert "left" in result.data["description"].lower()

    def test_straighten_elbow(self):
        result = classify_intent_regex("straighten your right elbow")
        assert result is not None
        assert result.type == "motion"
        assert "right" in result.data["description"].lower()

    def test_arm_out(self):
        result = classify_intent_regex("move your left arm out to the side")
        assert result is not None
        assert result.type == "motion"
        assert "left" in result.data["description"].lower()

    def test_explicit_angle(self):
        result = classify_intent_regex("raise your right arm to 45 degrees")
        assert result is not None
        assert "45" in result.data["description"]


class TestConversationIntents:
    def test_greeting(self):
        result = classify_intent_regex("hello")
        assert result is not None
        assert result.type == "conversation"

    def test_what_can_you_do(self):
        result = classify_intent_regex("what can you do")
        assert result is not None
        assert result.type == "conversation"


class TestCorrections:
    def test_faster_with_history(self):
        history = [{"role": "assistant", "content": "Raising arm"}]
        result = classify_intent_regex("faster", history=history)
        assert result is not None
        assert result.type == "motion"
        assert "faster" in result.data["description"].lower()

    def test_faster_without_history_is_conversation(self):
        result = classify_intent_regex("faster")
        assert result is not None
        assert result.type == "conversation"


class TestRetry:
    def test_try_again_with_history(self):
        history = [{"role": "assistant", "content": "Raising arm"}]
        result = classify_intent_regex("try again", history=history)
        assert result is not None
        assert result.type == "immediate"
        assert result.data["intent"] == "rollback_and_retry"

    def test_try_again_without_history_is_conversation(self):
        result = classify_intent_regex("try again")
        assert result is not None
        assert result.type == "conversation"


class TestNoMatch:
    def test_genuinely_ambiguous(self):
        result = classify_intent_regex("do something cool")
        assert result is None


class TestResponseMetadata:
    def test_regex_response_includes_classifier_and_reason(self):
        result = classify_intent_regex("follow me")
        assert result is not None
        response = result.to_response()
        assert response["classifier"] == "regex"
        assert response["reason"]
        assert response["type"] == "immediate"


class TestRegexPitfalls:
    def test_lower_your_right_arm_is_motion_not_correction(self):
        """Regression guard: 'lower your right arm' must be a direct motion."""
        result = classify_intent_regex("lower your right arm")
        assert result is not None
        assert result.type == "motion"
        assert "right" in result.data["description"].lower()

    def test_bare_done_only_triggers_exit(self):
        """The exit pattern must not fire on unrelated phrases containing 'done'."""
        result = classify_intent_regex("I'm almost done thinking")
        assert result is None or result.data.get("intent") != "exit"

    def test_done_exclamation_triggers_exit(self):
        result = classify_intent_regex("done!")
        assert result is not None
        assert result.type == "immediate"
        assert result.data["intent"] == "exit"


class TestPydanticResponseShape:
    def test_motion_response_matches_intent_schema(self):
        result = classify_intent_regex("turn your head left")
        assert result is not None
        response = result.to_response()
        assert response["type"] == "motion"
        assert "description" in response
        assert response["classifier"] == "regex"
        assert "reason" in response

    def test_immediate_response_matches_intent_schema(self):
        result = classify_intent_regex("follow me")
        assert result is not None
        response = result.to_response()
        assert response["type"] == "immediate"
        assert response["intent"] == "follow_start"

    def test_naming_response_includes_optional_name(self):
        result = classify_intent_regex("name this pose superhero")
        assert result is not None
        response = result.to_response()
        assert response["type"] == "immediate"
        assert response["intent"] == "naming"
        assert response["name"] == "superhero"
