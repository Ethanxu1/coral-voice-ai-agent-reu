"""Tests for motion sign validation and auto-correction."""

from app.validation import correct_motion_sign, validate_motion_sign


class TestHeadSigns:
    def test_head_left_negative(self):
        warnings = validate_motion_sign("turn head left", {"head_pan": 0.5})
        assert any("HEAD LEFT" in w for w in warnings)
        corrected = correct_motion_sign("turn head left", {"head_pan": 0.5})
        assert corrected["head_pan"] == -0.5

    def test_head_right_positive(self):
        warnings = validate_motion_sign("turn head right", {"head_pan": -0.5})
        assert any("HEAD RIGHT" in w for w in warnings)
        corrected = correct_motion_sign("turn head right", {"head_pan": -0.5})
        assert corrected["head_pan"] == 0.5

    def test_head_up_positive(self):
        warnings = validate_motion_sign("tilt head up", {"head_tilt": -0.5})
        assert any("HEAD UP" in w for w in warnings)
        corrected = correct_motion_sign("tilt head up", {"head_tilt": -0.5})
        assert corrected["head_tilt"] == 0.5

    def test_head_down_negative(self):
        warnings = validate_motion_sign("look down", {"head_tilt": 0.5})
        assert any("HEAD DOWN" in w for w in warnings)
        corrected = correct_motion_sign("look down", {"head_tilt": 0.5})
        assert corrected["head_tilt"] == -0.5


class TestElbowRotateSigns:
    def test_left_forearm_in_negative(self):
        warnings = validate_motion_sign("rotate left forearm in", {"l_el_pitch": 0.5})
        assert any("LEFT forearm IN" in w for w in warnings)
        corrected = correct_motion_sign("rotate left forearm in", {"l_el_pitch": 0.5})
        assert corrected["l_el_pitch"] == -0.5

    def test_left_forearm_out_positive(self):
        warnings = validate_motion_sign("rotate left forearm out", {"l_el_pitch": -0.5})
        assert any("LEFT forearm OUT" in w for w in warnings)
        corrected = correct_motion_sign("rotate left forearm out", {"l_el_pitch": -0.5})
        assert corrected["l_el_pitch"] == 0.5

    def test_right_forearm_in_positive(self):
        warnings = validate_motion_sign("rotate right forearm in", {"r_el_pitch": -0.5})
        assert any("RIGHT forearm IN" in w for w in warnings)
        corrected = correct_motion_sign("rotate right forearm in", {"r_el_pitch": -0.5})
        assert corrected["r_el_pitch"] == 0.5

    def test_right_forearm_out_negative(self):
        warnings = validate_motion_sign("rotate right forearm out", {"r_el_pitch": 0.5})
        assert any("RIGHT forearm OUT" in w for w in warnings)
        corrected = correct_motion_sign("rotate right forearm out", {"r_el_pitch": 0.5})
        assert corrected["r_el_pitch"] == -0.5


class TestCorrectSignsNoChangeWhenCorrect:
    def test_correct_signs_left(self):
        joints = {"head_pan": -0.5, "head_tilt": 0.5, "l_el_pitch": -0.5, "r_el_pitch": 0.5}
        assert validate_motion_sign("turn head left and tilt up, left forearm in, right forearm in", joints) == []
        assert correct_motion_sign("turn head left and tilt up, left forearm in, right forearm in", joints) == joints
