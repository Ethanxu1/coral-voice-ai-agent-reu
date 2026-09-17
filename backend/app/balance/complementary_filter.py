"""Complementary filter — fuses raw accelerometer + gyroscope readings into
a stable attitude estimate, for real hardware where (unlike sim) there's no
ground-truth orientation sensor to read directly.

Why a filter is needed here and wasn't needed in sim_source.py: the
accelerometer alone gives an absolute tilt reading but is corrupted by any
real linear acceleration (a step, a push, a servo twitch) — it assumes
"whatever it measures is gravity" and gets it wrong the moment the robot
actually moves. The gyroscope alone gives a clean, low-noise rate, but
integrating it drifts unboundedly over time with no way to know when it's
wrong. A complementary filter blends both: mostly trust the integrated
gyro moment-to-moment (responsive, no noise), but continuously pull back
toward what the accelerometer implies over a slow time constant, so drift
never accumulates. This is the standard, simplest AHRS technique — not a
Kalman filter — which is appropriate here: a standing-balance controller
only needs "which way is down, right now," not a navigation-grade
estimate.

Axis convention — CORRECTED 2026-09-17: the 2026-09-14 "confirmation"
below had roll and pitch swapped.
    accel_roll  = atan2(ax, ay)   -- CONFIRMED 2026-09-17 with two clean,
                                     isolated real-hardware tests: a
                                     genuine sideways lean (lifting one
                                     foot so weight shifts onto the other
                                     leg — mechanically constrained, not a
                                     freehand tilt) swung ax hard (up to
                                     0.81g) while az stayed at baseline
                                     (~0.03-0.07g); a genuine forward lean
                                     did the opposite — az swung hard
                                     (0.53g) while ax stayed at baseline
                                     (~0.00g). Two independent,
                                     mutually-exclusive axis responses is
                                     about as clean as real data gets.
    accel_pitch = atan2(az, ay)   -- Follows from the same two tests
                                     above (az is the axis a forward lean
                                     moves) — an ax/az swap can't be right
                                     for one of these and wrong for the
                                     other, they're the two horizontal
                                     components of one 3-axis reading.

What was wrong before: the 2026-09-14 test used atan2(az, ay) for roll
and seemed confirmed (standing ~3 deg, "right tilt" ~81 deg) — but that
right-tilt data point (accel=(-0.024, 0.15, 0.98), still locked into
test_complementary_filter.py's real-hardware tests) has az swinging to
0.98 while ax stays near zero, the exact signature 2026-09-17's
dedicated forward-lean test independently produced. The 2026-09-14 test
was very likely a forward/pitch-type tilt that got mislabeled as "tilt
toward its own right" — freehand tilting by hand is easy to apply along
the wrong axis without a mechanically constrained motion to anchor it
(the same difficulty that stalled the original pitch attempts that same
day). Full account of both the original mislabeling and the correction:
docs/balance-controller-progress.md Phase 3.

roll_rate/pitch_rate (from gx_dps/gy_dps) were NOT touched by this fix —
that pairing is a separate, still-unverified assumption. Confirming it
needs a controlled constant-rate ROTATION, not just a held static tilt
(all a dedicated axis check like the one above can produce by hand) — a
harder test, not yet attempted. Do not assume it's right just because
the accel formula was fixed.
"""

from __future__ import annotations

import math

try:
    from app.balance.controller import AttitudeReading
except ImportError:
    from controller import AttitudeReading  # flat Pi deployment (see balance_loop.py)


class ComplementaryFilter:
    """Stateful — call update() once per sample, in chronological order.
    One instance per balance loop; not safe to share across threads."""

    def __init__(self, alpha: float = 0.98):
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        self.alpha = alpha
        self._pitch_rad = 0.0
        self._roll_rad = 0.0

    def reset(self) -> None:
        self._pitch_rad = 0.0
        self._roll_rad = 0.0

    def update(
        self,
        accel_g: tuple[float, float, float],
        gyro_deg_s: tuple[float, float, float],
        dt: float,
    ) -> AttitudeReading:
        """accel_g: (ax, ay, az) in g — the first 3 floats of
        ainex_sdk.Board().get_imu(). gyro_deg_s: the next 3 floats,
        degrees/second (the sensor's native unit — converted to rad/s
        here, not by the caller, matching this project's convention of
        converting units at the hardware boundary rather than pushing
        that onto every caller). dt: seconds since the last update() call.
        """
        if dt <= 0:
            raise ValueError(f"dt must be positive, got {dt}")

        ax, ay, az = accel_g
        gx_dps, gy_dps, _gz_dps = gyro_deg_s
        roll_rate = math.radians(gx_dps)
        pitch_rate = math.radians(gy_dps)

        accel_roll = math.atan2(ax, ay)
        accel_pitch = math.atan2(az, ay)

        self._roll_rad = (
            self.alpha * (self._roll_rad + roll_rate * dt)
            + (1 - self.alpha) * accel_roll
        )
        self._pitch_rad = (
            self.alpha * (self._pitch_rad + pitch_rate * dt)
            + (1 - self.alpha) * accel_pitch
        )

        return AttitudeReading(
            pitch_rad=self._pitch_rad,
            roll_rad=self._roll_rad,
            pitch_rate=pitch_rate,
            roll_rate=roll_rate,
        )
