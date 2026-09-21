"""Standing-balance background loop (Pi side) — roll only, off by default.

Runs BalanceController continuously against the real IMU, adding a small
bounded correction on top of the robot's centered ('stand') roll joints.
Kept as its own background thread, separate from server.py's HTTP request
handlers — a continuous sense/compute/write loop can't live inside a
handler that blocks until one /move finishes (docs/balance-controller.md
§3).

Roll only, deliberately. Pitch is NOT wired in here: the real IMU's pitch
axis convention is still unconfirmed after 5 real hardware attempts (see
complementary_filter.py's docstring and
docs/balance-controller-progress.md Phase 3) — driving a correction from
an unverified sign onto a physical robot is exactly what this project's
verify-before-trust discipline exists to prevent. Roll's convention *is*
confirmed against real hardware, but the controller's correction
direction — does commanding these joints this way actually reduce a real
tilt — is still an open question from Phase 1's inconclusive sim
closed-loop test. That's why this loop starts OFF and stays off until
explicitly started via HTTP, and why the first real use of it should be
the single-shot sign check described in
docs/balance-controller-progress.md, not turning this loop on and hoping.

Deploy alongside controller.py, complementary_filter.py,
hardware_angle_utils.py and servo_config.py (all from backend/app/balance/
and backend/app/robot/) as sibling files in the same nodes/ directory as
server.py and body.py — this script and the modules it imports use flat,
same-directory imports (`from controller import ...`, not
`app.balance.controller`), matching how every Pi node in this repo is a
standalone file, not an installed package. Each of those four modules has
a try/except import fallback specifically so they work both ways — as
part of the `app` package (Mac, tested) and as flat sibling files (Pi).

Achievable loop rate — not a design target, a real constraint: every
tick's servo write goes through body.py's blocking /body_commands
service, which sleeps (frame_duration_ms/1000 + 0.1s) per frame
(body.py's _handle_command) regardless of how small a duration this loop
requests. That floor alone is ~0.1s, before the IMU read or anything
else — so the real achievable rate is roughly ≤10 Hz, not the 50 Hz
servo-bus ceiling the plan describes as the theoretical maximum. This
loop measures its own actual per-tick time (dt fed to the filter and
controller is always the real elapsed time, never assumed), so the
control math stays correct at whatever rate it actually achieves — but
the rate itself has not been measured on real hardware yet. Log
`[balance] tick took Xs` if that's ever needed; not added here to avoid
spamming rospy's log at ~10 Hz by default.

Zero-bias calibration (added 2026-09-21, live hardware finding): the
real IMU reads a real robot standing level, feet flat, as ~4 deg of
roll — confirmed a sensor-mounting offset, not a real body lean, by
visually checking the robot with ankles at true neutral (both feet
flat, looked level to the eye) while the sensor still reported ~4 deg.
Before this fix, the loop had no way to tell that constant bias apart
from genuine tilt, so it perpetually "corrected" a disturbance that
wasn't really there — visibly holding one foot's outer edge lifted even
at rest, with nothing pushing on the robot. `start()` now samples
`_CALIBRATION_SAMPLES` raw readings (assuming the robot is
approximately level at that moment — true in the normal use pattern,
since starting the loop happens right after getting the robot standing)
and treats their average as the new zero point for every subsequent
tick's roll reading. Recalibrates fresh on every `start()` rather than
persisting across runs, since that's simpler and self-corrects if the
robot's actual resting posture or the sensor's mounting ever changes
slightly between sessions.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from controller import AttitudeReading, BalanceController, BalanceGains, apply_balance_offset
from complementary_filter import ComplementaryFilter
from hardware_angle_utils import HW_SERVO_LIMITS, HW_STAND_RAD, hardware_units_to_rad, rad_to_hardware_units

# The only joints this loop is ever allowed to write. Pitch channels
# (l/r_ank_pitch, l/r_hip_pitch) are absent on purpose — see module
# docstring — even though BalanceController.update() computes them too;
# _tick() below discards them before they ever reach a servo.
_ROLL_JOINTS: Tuple[str, ...] = ("l_ank_roll", "r_ank_roll", "l_hip_roll", "r_hip_roll")

# Nominal request only — see module docstring on why the real rate is lower.
_TICK_SECONDS = 0.05

# How many raw IMU samples to average at start() for the zero-bias
# calibration below, and the gap between them. ~15 samples over ~0.5s —
# enough to smooth out per-sample noise without making POST /balance/start
# noticeably slow to respond.
_CALIBRATION_SAMPLES = 15
_CALIBRATION_SAMPLE_INTERVAL_S = 0.03


class _SimpleLimit:
    """Minimal stand-in for validation.JointLimit (min/max + .clamp()).
    Avoids deploying validation.py's own import chain to the Pi for just
    four joints; built the same way validation.py's _from_hw() builds the
    real one, from the same HW_SERVO_LIMITS source of truth."""

    __slots__ = ("lo", "hi")

    def __init__(self, lo: float, hi: float):
        self.lo, self.hi = lo, hi

    def clamp(self, value: float) -> float:
        return max(self.lo, min(self.hi, value))


def _build_roll_joint_limits() -> Dict[str, _SimpleLimit]:
    limits: Dict[str, _SimpleLimit] = {}
    for joint in _ROLL_JOINTS:
        lo_pulse, hi_pulse = HW_SERVO_LIMITS[joint]
        a = hardware_units_to_rad(lo_pulse, joint)
        b = hardware_units_to_rad(hi_pulse, joint)
        limits[joint] = _SimpleLimit(min(a, b), max(a, b))
    return limits


class BalanceLoop:
    """Background thread running BalanceController's roll channels against
    the real IMU. OFF by default — start()/stop() are the only way it
    runs; nothing here starts it automatically."""

    def __init__(
        self,
        board,
        call_body_service: Callable[[List[Tuple[Dict[str, int], int]]], float],
        move_lock: threading.Lock,
        gains: Optional[BalanceGains] = None,
    ):
        self._board = board
        self._call_body_service = call_body_service
        self._move_lock = move_lock
        self._joint_limits = _build_roll_joint_limits()
        # Most roll joints sit at their centered pulse (500 -- exactly
        # 0 rad) at stand, but NOT all of them: r_ank_roll has a real,
        # nonzero HW_STAND_RAD entry (-0.0698 rad) -- a genuine
        # asymmetry between the two ankle-roll servos' calibration, not
        # a typo. Found 2026-09-21 via a simulated resting-state test:
        # assuming 0.0 for every roll joint here (the old code) made
        # rad_to_hardware_units() silently miscalibrate r_ank_roll by
        # that whole offset, converging to the wrong resting pulse
        # (483, not 500) even once the controller's own error was
        # genuinely zero. HW_STAND_RAD.get() defaults to 0.0 for joints
        # with no entry (l_ank_roll, both hip_roll), matching their
        # actual stand-pose value -- see hardware_angle_utils.py's own
        # docstring on what an absent entry means.
        self._baseline_rad: Dict[str, float] = {j: HW_STAND_RAD.get(j, 0.0) for j in _ROLL_JOINTS}
        self._filter = ComplementaryFilter()
        self._controller = BalanceController(gains)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_tick_t: Optional[float] = None
        self._roll_bias_rad = 0.0
        self.last_error: Optional[str] = None
        self.tick_count = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _calibrate_roll_bias(self) -> float:
        """Average a handful of raw accel-only roll readings and return
        that as the sensor's zero-bias offset — see module docstring.
        Assumes the robot is approximately level right now (true at the
        moment start() is normally called). Falls back to 0.0 (today's
        old, uncalibrated behavior) if the board never returns usable
        data, rather than raising and blocking start() entirely."""
        samples: List[float] = []
        for _ in range(_CALIBRATION_SAMPLES):
            raw = self._board.get_imu()
            if raw is not None and len(raw) >= 2:
                ax, ay = raw[0], raw[1]
                samples.append(math.atan2(ax, ay))
            time.sleep(_CALIBRATION_SAMPLE_INTERVAL_S)
        if not samples:
            return 0.0
        return sum(samples) / len(samples)

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._filter.reset()
        self._controller.reset()
        self._last_tick_t = None
        self._roll_bias_rad = self._calibrate_roll_bias()
        self.last_error = None
        self.tick_count = 0
        self._thread = threading.Thread(target=self._run, name="balance-loop", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            tick_start = time.monotonic()
            try:
                self._tick()
                self.tick_count += 1
            except Exception as e:  # noqa: BLE001 — a bad tick must not kill the loop silently
                self.last_error = str(e)
            elapsed = time.monotonic() - tick_start
            time.sleep(max(0.0, _TICK_SECONDS - elapsed))

    def _tick(self) -> None:
        raw = self._board.get_imu()
        if raw is None or len(raw) < 6:
            return  # transient IMU miss — routine, matches ainex_sdk's own demo scripts; skip and retry next tick

        now = time.monotonic()
        dt = _TICK_SECONDS if self._last_tick_t is None else max(1e-3, now - self._last_tick_t)
        self._last_tick_t = now

        accel_g = (raw[0], raw[1], raw[2])
        gyro_dps = (raw[3], raw[4], raw[5])
        filtered = self._filter.update(accel_g, gyro_dps, dt)
        # Subtract the sensor's zero-bias offset (measured once at
        # start() — see module docstring) so the controller reacts to
        # real tilt, not the IMU's own mounting offset.
        attitude = AttitudeReading(
            pitch_rad=filtered.pitch_rad,
            roll_rad=filtered.roll_rad - self._roll_bias_rad,
            pitch_rate=filtered.pitch_rate,
            roll_rate=filtered.roll_rate,
        )

        offset = self._controller.update(attitude, dt)
        roll_offset = {j: offset[j] for j in _ROLL_JOINTS}  # pitch channels computed but discarded — see module docstring

        corrected_rad = apply_balance_offset(self._baseline_rad, roll_offset, joint_limits=self._joint_limits)
        corrected_pulse = {j: rad_to_hardware_units(rad, j) for j, rad in corrected_rad.items()}

        if not self._move_lock.acquire(blocking=False):
            return  # a /move is already in flight — skip this tick rather than contend for the servo bus
        try:
            sequence = [(corrected_pulse, int(_TICK_SECONDS * 1000))]
            self._call_body_service(sequence)
        finally:
            self._move_lock.release()
