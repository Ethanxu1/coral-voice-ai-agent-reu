"""Tests for child-speech normalization used before regex intent matching."""

from app.llm.normalize_speech import normalize_for_regex


class TestNormalizeForRegex:
    def test_lowercases_input(self):
        assert normalize_for_regex("RaIsE YouR Arm") == "raise your arm"

    def test_strips_leading_fillers(self):
        assert normalize_for_regex("um uh like raise your arm") == "raise your arm"

    def test_expands_contractions(self):
        assert normalize_for_regex("I wanna raise my arm") == "i want to raise my arm"
        assert normalize_for_regex("I'm gonna lift it up") == "i'm going to raise"
        assert normalize_for_regex("Lemme see") == "let me see"

    def test_maps_motion_synonyms(self):
        assert normalize_for_regex("make it go up") == "raise"
        assert normalize_for_regex("put it down") == "lower"
        assert normalize_for_regex("lift it up") == "raise"
        assert normalize_for_regex("move it out") == "extend"
        assert normalize_for_regex("turn it left") == "turn left"

    def test_collapses_repeated_words(self):
        assert normalize_for_regex("raise raise your arm") == "raise your arm"
        assert normalize_for_regex("the the the robot") == "the robot"

    def test_combined_transforms(self):
        assert (
            normalize_for_regex("Um, like, I wanna make it go up")
            == "i want to raise"
        )
