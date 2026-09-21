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


class TestIntegralTerm:
    """ankle_ki, added 2026-09-21 to close the steady-state residual a
    pure-PD controller always leaves against a constant bias — see
    docs/balance-controller-progress.md Phase 3, "Continuous loop
    deployment." Defaults to 0.0 (off); these tests exercise it
    explicitly enabled. Rate limiter given a huge ceiling throughout so
    it never masks the integral's own effect on the raw output."""

    def test_default_ki_zero_matches_pure_pd_forever(self):
        """The whole point of defaulting ankle_ki to 0.0: every existing
        PD-only test (this file, unmodified) stays correct proof of this,
        but also assert it directly — many ticks of a constant error
        should never make a ki=0.0 controller's output grow beyond what a
        single P+D tick already gives, unlike a real integral term."""
        gains = BalanceGains(max_rate_rad_per_s=1000.0, max_correction_rad=10.0)
        controller = BalanceController(gains)
        attitude = AttitudeReading(pitch_rad=0.2, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        first = controller.update(attitude, dt=0.02)["l_ank_pitch"]
        for _ in range(50):
            latest = controller.update(attitude, dt=0.02)["l_ank_pitch"]
        assert latest == pytest.approx(first)

    def test_integral_grows_the_correction_beyond_pd_alone(self):
        """With ki>0 and a constant error, later ticks should produce a
        LARGER-magnitude correction than the very first tick — the
        signature of accumulation, absent when ki=0.0 (test above)."""
        gains = BalanceGains(
            ankle_ki=0.5, integral_max_rad=10.0,  # cap way out of reach here
            max_rate_rad_per_s=1000.0, max_correction_rad=10.0,
        )
        controller = BalanceController(gains)
        attitude = AttitudeReading(pitch_rad=0.2, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        first = abs(controller.update(attitude, dt=0.02)["l_ank_pitch"])
        for _ in range(50):
            latest = abs(controller.update(attitude, dt=0.02)["l_ank_pitch"])
        assert latest > first

    def test_integral_accumulator_is_clamped_anti_windup(self):
        """However long a disturbance persists, the ACCUMULATED integral
        itself must never exceed integral_max_rad — the anti-windup
        guarantee. Checked on the internal accumulator directly (not just
        the final output) since the output is also shaped by
        ankle_saturation_rad/max_correction_rad/the rate limiter, which
        would make an output-only check ambiguous about which cap is
        actually doing the limiting."""
        gains = BalanceGains(
            ankle_ki=0.5, integral_max_rad=0.05,
            max_rate_rad_per_s=1000.0, max_correction_rad=10.0, ankle_saturation_rad=10.0,
        )
        controller = BalanceController(gains)
        attitude = AttitudeReading(pitch_rad=5.0, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        for _ in range(500):
            controller.update(attitude, dt=0.02)
        assert abs(controller._integral["ankle_pitch"]) <= gains.integral_max_rad + 1e-12

    def test_integral_accumulates_even_inside_the_deadband(self):
        """Deliberately different from P/D: the integral accumulates the
        RAW attitude, not the deadbanded error, specifically so it can
        close a residual smaller than deadband_rad. Found necessary via
        live sim testing 2026-09-21 — the actual steady-state residual
        this term exists to close (a few tenths of a degree) is itself
        smaller than deadband_rad (0.57 deg default); gating the
        integral on the same deadbanded error P/D use meant it had
        nothing to accumulate at exactly the error size it was added
        for. See the comment in update() for the full account."""
        gains = BalanceGains(
            ankle_ki=0.5, deadband_rad=0.05,
            max_rate_rad_per_s=1000.0, max_correction_rad=10.0,
        )
        controller = BalanceController(gains)
        tiny_tilt = AttitudeReading(pitch_rad=0.01, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        for _ in range(100):
            controller.update(tiny_tilt, dt=0.02)
        assert controller._integral["ankle_pitch"] != 0.0

    def test_integral_still_bounded_even_inside_the_deadband(self):
        """The anti-windup cap applies regardless of whether the input is
        inside or outside the P/D deadband — many ticks of even a tiny
        tilt must still respect integral_max_rad."""
        gains = BalanceGains(
            ankle_ki=0.5, deadband_rad=0.05, integral_max_rad=0.02,
            max_rate_rad_per_s=1000.0, max_correction_rad=10.0,
        )
        controller = BalanceController(gains)
        tiny_tilt = AttitudeReading(pitch_rad=0.01, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        for _ in range(1000):
            controller.update(tiny_tilt, dt=0.02)
        assert abs(controller._integral["ankle_pitch"]) <= gains.integral_max_rad + 1e-12

    def test_reset_clears_the_integral_too(self):
        gains = BalanceGains(
            ankle_ki=0.5, max_rate_rad_per_s=1000.0, max_correction_rad=10.0,
        )
        controller = BalanceController(gains)
        attitude = AttitudeReading(pitch_rad=0.2, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        for _ in range(20):
            controller.update(attitude, dt=0.02)
        assert controller._integral["ankle_pitch"] != 0.0  # sanity: it did accumulate
        controller.reset()
        assert controller._integral["ankle_pitch"] == 0.0
        assert controller._integral["ankle_roll"] == 0.0

    def test_integral_direction_opposes_the_tilt_same_as_p_term(self):
        """Sign check: a positive (forward/right) tilt held over many
        ticks must integrate toward a NEGATIVE correction (opposing it),
        matching the existing P-term sign convention — an integral term
        with the wrong sign would actively push the robot further over
        the longer a disturbance persists, worse than no integral at
        all."""
        gains = BalanceGains(
            ankle_ki=0.5, integral_max_rad=10.0,
            max_rate_rad_per_s=1000.0, max_correction_rad=10.0,
        )
        controller = BalanceController(gains)
        attitude = AttitudeReading(pitch_rad=0.2, roll_rad=0.0, pitch_rate=0.0, roll_rate=0.0)
        for _ in range(20):
            controller.update(attitude, dt=0.02)
        assert controller._integral["ankle_pitch"] > 0.0  # accumulated positive error
        offsets = controller.update(attitude, dt=0.02)
        assert offsets["l_ank_pitch"] < 0.0  # but the resulting correction opposes it

    def test_hip_channel_has_no_integral_state(self):
        """Deliberately scoped to ankle only — see BalanceGains.ankle_ki's
        docstring. Confirms there's no hip_pitch/hip_roll key hiding in
        the integral dict that a future change might assume exists."""
        controller = BalanceController()
        assert set(controller._integral.keys()) == {"ankle_pitch", "ankle_roll"}


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
