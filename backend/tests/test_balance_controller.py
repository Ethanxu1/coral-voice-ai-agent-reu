"""Tests for the two-tier ankle/hip balance controller (backend/app/balance).

Written before/alongside the implementation, per AGENTS.md's TDD-first rule
for feature work. These cover the controller's pure math in isolation — no
MuJoCo, no hardware, no sensor wiring, matching the module's own "read
attitude + rate in, joint offset out" boundary. Sign conventions, gain
values, and real-hardware behavior are all still unverified — see
docs/balance-controller-progress.md.
"""

import pytest

from app.balance.controller import (
    AttitudeReading,
    BalanceController,
    BalanceGains,
    apply_balance_offset,
)

_LEVEL = AttitudeReading(pitch_rad=0.0, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)


def _all_joints(offsets: dict[str, float]) -> set[str]:
    return set(offsets.keys())


class TestChannelShape:
    def test_returns_exactly_the_eight_balance_joints(self):
        controller = BalanceController()
        offsets = controller.update(_LEVEL, dt=0.02)
        assert _all_joints(offsets) == {
            "l_ank_pitch", "r_ank_pitch", "l_ank_roll", "r_ank_roll",
            "l_hip_pitch", "r_hip_pitch", "l_hip_roll", "r_hip_roll",
        }

    def test_level_and_still_produces_zero_correction(self):
        controller = BalanceController()
        offsets = controller.update(_LEVEL, dt=0.02)
        assert all(v == 0.0 for v in offsets.values())


class TestDeadband:
    def test_tilt_inside_deadband_is_ignored(self):
        gains = BalanceGains(deadband_rad=0.05)
        controller = BalanceController(gains)
        attitude = AttitudeReading(pitch_rad=0.03, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        offsets = controller.update(attitude, dt=0.02)
        assert offsets["l_ank_pitch"] == 0.0
        assert offsets["r_ank_pitch"] == 0.0

    def test_tilt_outside_deadband_produces_correction(self):
        gains = BalanceGains(deadband_rad=0.01, max_rate_rad_per_s=1000.0)
        controller = BalanceController(gains)
        attitude = AttitudeReading(pitch_rad=0.05, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        offsets = controller.update(attitude, dt=0.02)
        assert offsets["l_ank_pitch"] != 0.0


class TestAnkleStrategy:
    def test_small_forward_lean_only_engages_ankle(self):
        gains = BalanceGains(ankle_saturation_rad=0.5, max_rate_rad_per_s=1000.0)
        controller = BalanceController(gains)
        attitude = AttitudeReading(pitch_rad=0.05, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        offsets = controller.update(attitude, dt=0.02)
        assert offsets["l_ank_pitch"] != 0.0
        assert offsets["l_hip_pitch"] == 0.0
        assert offsets["r_hip_pitch"] == 0.0

    def test_forward_lean_corrects_opposite_sign(self):
        """A positive (forward) pitch error must produce a correction that
        opposes it — this is the one thing that must never be backwards,
        or the controller pushes the robot over instead of catching it."""
        gains = BalanceGains(max_rate_rad_per_s=1000.0)
        controller = BalanceController(gains)
        attitude = AttitudeReading(pitch_rad=0.05, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        offsets = controller.update(attitude, dt=0.02)
        assert offsets["l_ank_pitch"] < 0.0

    def test_larger_tilt_produces_larger_correction_before_saturation(self):
        gains = BalanceGains(ankle_saturation_rad=0.5, max_rate_rad_per_s=1000.0)
        small = BalanceController(gains).update(
            AttitudeReading(0.02, 0.0, 0.0, 0.0), dt=0.02
        )
        large = BalanceController(gains).update(
            AttitudeReading(0.10, 0.0, 0.0, 0.0), dt=0.02
        )
        assert abs(large["l_ank_pitch"]) > abs(small["l_ank_pitch"])

    def test_both_legs_move_symmetrically(self):
        gains = BalanceGains(max_rate_rad_per_s=1000.0)
        controller = BalanceController(gains)
        attitude = AttitudeReading(pitch_rad=0.05, roll_rad=0.03, pitch_rate=0.0, roll_rate=0.0)
        offsets = controller.update(attitude, dt=0.02)
        assert offsets["l_ank_pitch"] == offsets["r_ank_pitch"]
        assert offsets["l_ank_roll"] == offsets["r_ank_roll"]
        assert offsets["l_hip_pitch"] == offsets["r_hip_pitch"]
        assert offsets["l_hip_roll"] == offsets["r_hip_roll"]


class TestHipStrategy:
    def test_large_tilt_engages_hip_once_ankle_saturates(self):
        gains = BalanceGains(
            ankle_saturation_rad=0.05, hip_kp=0.4, max_rate_rad_per_s=1000.0
        )
        controller = BalanceController(gains)
        attitude = AttitudeReading(pitch_rad=0.5, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        offsets = controller.update(attitude, dt=0.02)
        assert offsets["l_hip_pitch"] != 0.0
        # Ankle stays at its saturation bound, doesn't grow further.
        assert abs(offsets["l_ank_pitch"]) == pytest.approx(gains.ankle_saturation_rad)

    def test_hip_correction_also_opposes_the_tilt(self):
        gains = BalanceGains(ankle_saturation_rad=0.05, max_rate_rad_per_s=1000.0)
        controller = BalanceController(gains)
        attitude = AttitudeReading(pitch_rad=0.5, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        offsets = controller.update(attitude, dt=0.02)
        assert offsets["l_hip_pitch"] < 0.0

    def test_roll_and_pitch_hip_engagement_are_independent(self):
        """A large pitch tilt alone must not spuriously engage the roll
        hip channel, and vice versa."""
        gains = BalanceGains(ankle_saturation_rad=0.05, max_rate_rad_per_s=1000.0)
        controller = BalanceController(gains)
        attitude = AttitudeReading(pitch_rad=0.5, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        offsets = controller.update(attitude, dt=0.02)
        assert offsets["l_hip_pitch"] != 0.0
        assert offsets["l_hip_roll"] == 0.0


class TestSafetyBounds:
    def test_max_correction_rad_caps_ankle_even_with_extreme_tilt(self):
        gains = BalanceGains(max_correction_rad=0.2, max_rate_rad_per_s=1000.0)
        controller = BalanceController(gains)
        attitude = AttitudeReading(pitch_rad=10.0, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        offsets = controller.update(attitude, dt=0.02)
        assert abs(offsets["l_ank_pitch"]) <= gains.max_correction_rad

    def test_max_correction_rad_caps_hip_even_with_extreme_tilt(self):
        gains = BalanceGains(
            ankle_saturation_rad=0.01, max_correction_rad=0.2, max_rate_rad_per_s=1000.0
        )
        controller = BalanceController(gains)
        attitude = AttitudeReading(pitch_rad=10.0, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        offsets = controller.update(attitude, dt=0.02)
        assert abs(offsets["l_hip_pitch"]) <= gains.max_correction_rad

    def test_rate_limit_bounds_a_single_tick_change(self):
        gains = BalanceGains(max_rate_rad_per_s=1.0, max_correction_rad=10.0)
        controller = BalanceController(gains)
        attitude = AttitudeReading(pitch_rad=5.0, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        dt = 0.02
        offsets = controller.update(attitude, dt=dt)
        assert abs(offsets["l_ank_pitch"]) <= gains.max_rate_rad_per_s * dt + 1e-9

    def test_rate_limit_allows_convergence_over_multiple_ticks(self):
        gains = BalanceGains(
            max_rate_rad_per_s=50.0, max_correction_rad=10.0, ankle_saturation_rad=10.0
        )
        controller = BalanceController(gains)
        attitude = AttitudeReading(pitch_rad=0.2, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        first = controller.update(attitude, dt=0.02)["l_ank_pitch"]
        for _ in range(20):
            latest = controller.update(attitude, dt=0.02)["l_ank_pitch"]
        # A steady disturbance should converge toward a bigger correction
        # than the very first, rate-limited tick produced.
        assert abs(latest) >= abs(first)

    def test_reset_clears_rate_limiter_history(self):
        gains = BalanceGains(max_rate_rad_per_s=1.0, max_correction_rad=10.0)
        controller = BalanceController(gains)
        attitude = AttitudeReading(pitch_rad=5.0, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        for _ in range(50):
            controller.update(attitude, dt=0.02)
        controller.reset()
        # Immediately after reset, a single tick is rate-limited from zero
        # again, not from wherever the previous run left off.
        offsets = controller.update(attitude, dt=0.02)
        assert abs(offsets["l_ank_pitch"]) <= gains.max_rate_rad_per_s * 0.02 + 1e-9


class TestApplyBalanceOffset:
    def test_adds_offset_to_baseline(self):
        baseline = {"l_ank_pitch": 0.1, "r_ank_pitch": -0.1}
        offset = {"l_ank_pitch": 0.02, "r_ank_pitch": 0.02}
        result = apply_balance_offset(baseline, offset, joint_limits={})
        assert result["l_ank_pitch"] == pytest.approx(0.12)
        assert result["r_ank_pitch"] == pytest.approx(-0.08)

    def test_skips_offset_joints_missing_from_baseline(self):
        baseline = {"l_ank_pitch": 0.1}
        offset = {"l_ank_pitch": 0.02, "l_hip_pitch": 0.5}
        result = apply_balance_offset(baseline, offset, joint_limits={})
        assert "l_hip_pitch" not in result

    def test_clamps_through_joint_limits(self):
        from app.validation import JointLimit

        baseline = {"l_ank_pitch": 0.09}
        offset = {"l_ank_pitch": 0.5}
        limits = {"l_ank_pitch": JointLimit(min=-0.1, max=0.1)}
        result = apply_balance_offset(baseline, offset, joint_limits=limits)
        assert result["l_ank_pitch"] == pytest.approx(0.1)

    def test_default_joint_limits_are_the_real_hardware_derived_table(self):
        """Sanity check that the default path actually reaches the same
        JOINT_LIMITS every other dispatch path is clamped through, not a
        stub — an absurdly large offset must still come back in range."""
        baseline = {"l_ank_pitch": 0.0}
        offset = {"l_ank_pitch": 100.0}
        result = apply_balance_offset(baseline, offset)
        assert -1.0 < result["l_ank_pitch"] < 1.0
