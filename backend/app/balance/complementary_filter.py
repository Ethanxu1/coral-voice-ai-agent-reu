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

Axis convention — UNVERIFIED ON REAL HARDWARE, flagged deliberately:
    accel_roll  = atan2(ay, az)
    accel_pitch = atan2(-ax, hypot(ay, az))
This is the standard formula assuming the IMU's raw axes follow the same
roll-about-X / pitch-about-Y convention already empirically verified for
the simulator (backend/app/balance/sim_source.py, verified by actually
rotating the model and checking the sign — see
backend/tests/test_balance_sim_source.py). Using the same convention here
is a reasonable *starting* assumption, since the manufacturer built both
the mechanics and the IMU mounting, but it is NOT independently confirmed
for the physical board — sim_source.py's convention was checked by
rotating the model and reading a sensor; this one can only be checked by
physically tilting the real robot and reading /imu's raw output. See
docs/balance-controller-progress.md Phase 3 for that procedure. If tilting
the robot forward makes the reported pitch go negative instead of
positive, negate accel_pitch (and pitch_rate) below; same for roll.
"""

from __future__ import annotations

import math

from app.balance.controller import AttitudeReading


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

        accel_roll = math.atan2(ay, az)
        accel_pitch = math.atan2(-ax, math.hypot(ay, az))

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
