"""Tests for ComplementaryFilter (backend/app/balance/complementary_filter.py).

These verify the FILTER ALGORITHM — blending, integration, convergence —
using synthetic accel/gyro sequences, with accel_g=(0, 1, 0) as "upright."
That's not an arbitrary choice: it's what the real robot's IMU actually
reads when standing (confirmed 2026-09-14 — Y is the resting "up" axis on
this board, not Z as a generic IMU tutorial would assume). The roll
formula (atan2(az, ay)) is confirmed against real tilt data the same day;
pitch (atan2(ax, ay)) is not yet independently confirmed — see the module
docstring and docs/balance-controller-progress.md Phase 3.
"""

import math

import pytest

from app.balance.complementary_filter import ComplementaryFilter

_UPRIGHT = (0.0, 1.0, 0.0)  # (ax, ay, az) — confirmed against real hardware


class TestValidation:
    def test_alpha_must_be_between_zero_and_one(self):
        with pytest.raises(ValueError):
            ComplementaryFilter(alpha=1.0)
        with pytest.raises(ValueError):
            ComplementaryFilter(alpha=0.0)
        with pytest.raises(ValueError):
            ComplementaryFilter(alpha=-0.1)

    def test_dt_must_be_positive(self):
        f = ComplementaryFilter()
        with pytest.raises(ValueError):
            f.update(accel_g=_UPRIGHT, gyro_deg_s=(0, 0, 0), dt=0.0)
        with pytest.raises(ValueError):
            f.update(accel_g=_UPRIGHT, gyro_deg_s=(0, 0, 0), dt=-0.01)


class TestAtRest:
    def test_upright_at_rest_stays_near_zero(self):
        f = ComplementaryFilter()
        for _ in range(50):
            reading = f.update(accel_g=_UPRIGHT, gyro_deg_s=(0.0, 0.0, 0.0), dt=0.01)
        assert reading.pitch_rad == pytest.approx(0.0, abs=1e-9)
        assert reading.roll_rad == pytest.approx(0.0, abs=1e-9)
        assert reading.pitch_rate == 0.0
        assert reading.roll_rate == 0.0

    def test_reset_clears_accumulated_state(self):
        f = ComplementaryFilter()
        # Push it away from zero with a sustained gyro rate.
        for _ in range(20):
            f.update(accel_g=_UPRIGHT, gyro_deg_s=(50.0, 0.0, 0.0), dt=0.01)
        f.reset()
        reading = f.update(accel_g=_UPRIGHT, gyro_deg_s=(0.0, 0.0, 0.0), dt=0.01)
        assert reading.roll_rad == pytest.approx(0.0, abs=1e-9)


class TestConvergence:
    def test_converges_toward_accel_tilt_when_gyro_reports_no_rotation(self):
        """With gyro flat at zero, only the accel pull-back term acts, so
        repeated updates should walk the estimate toward what the
        accelerometer implies, even though a single update barely moves it."""
        f = ComplementaryFilter(alpha=0.9)  # lower alpha -> converges faster, easier to assert
        # roll = atan2(az, ay), so az=sin(target), ay=cos(target) implies
        # accel_roll == target exactly.
        target = math.radians(20)
        accel = (0.0, math.cos(target), math.sin(target))
        reading = None
        for _ in range(300):
            reading = f.update(accel_g=accel, gyro_deg_s=(0.0, 0.0, 0.0), dt=0.01)
        assert reading.roll_rad == pytest.approx(target, abs=1e-3)
        assert reading.pitch_rad == pytest.approx(0.0, abs=1e-6)

    def test_pure_consistent_rotation_tracks_the_analytic_angle(self):
        """When gyro and accel agree at every step (a constant-rate rotation
        where the accel vector is kept exactly consistent with the true
        angle), the filter shouldn't need its correction term at all — it
        should track the true angle closely regardless of alpha."""
        f = ComplementaryFilter(alpha=0.98)
        rate_deg_s = 15.0
        dt = 0.005
        steps = 400  # 2 seconds -> true angle reaches 30 degrees
        true_angle = 0.0
        reading = None
        for _ in range(steps):
            true_angle += math.radians(rate_deg_s) * dt
            accel = (0.0, math.cos(true_angle), math.sin(true_angle))
            reading = f.update(accel_g=accel, gyro_deg_s=(rate_deg_s, 0.0, 0.0), dt=dt)
        assert reading.roll_rad == pytest.approx(true_angle, abs=1e-3)


class TestRateConversion:
    def test_gyro_degrees_per_second_converted_to_radians(self):
        f = ComplementaryFilter()
        reading = f.update(accel_g=_UPRIGHT, gyro_deg_s=(90.0, 180.0, 0.0), dt=0.01)
        assert reading.roll_rate == pytest.approx(math.pi / 2)
        assert reading.pitch_rate == pytest.approx(math.pi)


class TestStatefulness:
    def test_state_persists_and_accumulates_across_calls(self):
        f = ComplementaryFilter(alpha=0.999)  # near-pure integration for this check
        first = f.update(accel_g=_UPRIGHT, gyro_deg_s=(100.0, 0.0, 0.0), dt=0.01)
        second = f.update(accel_g=_UPRIGHT, gyro_deg_s=(100.0, 0.0, 0.0), dt=0.01)
        assert second.roll_rad > first.roll_rad > 0.0


class TestRealHardwareReadings:
    """Not synthetic — the actual /imu values from the physical robot,
    2026-09-14 (see docs/balance-controller-progress.md Phase 3). Locks in
    that real standing data reads near-zero roll and real right-tilt data
    reads a large one, so a future change can't silently break the fit to
    the one real calibration point we have."""

    def test_standing_reading_is_near_level(self):
        f = ComplementaryFilter()
        reading = f.update(
            accel_g=(-0.0228271484375, 0.997314453125, 0.0537109375),
            gyro_deg_s=(0.0, 0.0, 0.0),
            dt=0.01,
        )
        assert abs(math.degrees(reading.roll_rad)) < 5

    def test_right_tilt_reading_is_a_large_roll(self):
        # Low alpha so one update reflects what the accel data implies,
        # rather than the default filter's slow multi-sample blend —
        # this test is about the formula applied to real data, not the
        # filter's settling time (that's what the Convergence tests cover).
        f = ComplementaryFilter(alpha=0.01)
        reading = f.update(
            accel_g=(-0.024169921875, 0.1507568359375, 0.9814453125),
            gyro_deg_s=(0.0, 0.0, 0.0),
            dt=0.01,
        )
        assert math.degrees(reading.roll_rad) > 60
