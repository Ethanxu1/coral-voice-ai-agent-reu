"""Tests for the system-intent matcher in app.services.intent."""

import pytest

from app.services.intent import classify_system_intent


class TestClassifySystemIntent:
    def test_follow_start_phrases(self):
        for phrase in ["follow me", "mirror my movements", "copy my moves"]:
            assert classify_system_intent(phrase) == "follow_start", phrase

    def test_follow_stop_does_not_require_active_follow(self):
        # Even if the backend thinks follow is not active, "stop following" must
        # still classify as a stop command so it is not reinterpreted as motion.
        assert classify_system_intent("stop following") == "follow_stop"
        assert classify_system_intent("stop following my movement") == "follow_stop"
        assert classify_system_intent("stop mirroring") == "follow_stop"

    def test_capture_phrases(self):
        for phrase in ["capture my pose", "take a picture", "copy my pose"]:
            assert classify_system_intent(phrase) == "capture_pose", phrase

    def test_save_phrases(self):
        for phrase in ["save this pose", "remember this", "keep this pose"]:
            assert classify_system_intent(phrase) == "save_current_pose", phrase

    def test_unmatched_falls_through(self):
        assert classify_system_intent("hello") is None
        assert classify_system_intent("what's your name") is None
