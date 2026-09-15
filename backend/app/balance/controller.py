"""Two-tier ankle/hip balance controller.

Pure, sensor-agnostic control logic for keeping the AiNex upright while
standing: reads torso attitude (roll/pitch) and angular rate, returns a
bounded joint-offset correction meant to be added on top of whatever pose
is currently commanded (live retargeting's output, a saved pose being
replayed, or just standing still) — it never replaces that pose, only
nudges it. See docs/balance-controller.md for the full design and
rationale; this module implements that doc's §3-4.

Deliberately has no MuJoCo or hardware dependency: "read attitude + rate
in, joint offset out" is the whole boundary, so the identical control
logic runs against MuJoCo's sensors in simulation and the Pi's onboard
IMU on real hardware without being rewritten (docs/balance-controller.md
§3, "Same algorithm, two sensor sources"). Wiring an actual sensor source
to this class is a separate, later piece of work — see
docs/balance-controller-progress.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BalanceGains:
    """Tunable constants.

    Defaults below are untuned placeholders, not measured values — get
    them into a reasonable range in simulation first, then re-tune by feel
    on hardware; docs/balance-controller.md §7 is explicit that sim gains
    do not transfer 1:1 to the real bus servos' response. Nothing here has
    been validated against either sim or hardware yet.
    """

    ankle_kp: float = 0.6
    ankle_kd: float = 0.05
    hip_kp: float = 0.4
    hip_kd: float = 0.03

    # Ankle-alone soft limit (rad) — beyond this, the hip strategy engages
    # on top of the (now-clamped) ankle correction.
    ankle_saturation_rad: float = 0.12

    # Hard safety ceiling (rad) on any single channel's offset, ankle or
    # hip alike — the last line of defense against a bad gain or a sensor
    # glitch commanding something dangerous. This is an offset added on
    # top of a baseline pose, not a joint's whole range, so it must stay
    # well inside the smallest per-joint HW_SERVO_LIMITS span
    # (hardware_angle_utils.py) — not validated against that yet.
    max_correction_rad: float = 0.20

    # Per-second rate cap (rad/s) on how fast any one channel's output can
    # change, so a sudden jump in the raw PD output can't reach the servo
    # bus in a single step. 3.0 (not the original 2.0) is the first
    # sim-tuned value here: a live push-response sweep on 2026-09-15 found
    # this was the actual bottleneck on post-push overshoot, not ankle_kd
    # (raising kd alone did nothing measurable in the same test) — 2.0 gave
    # a peak overshoot of -1.96 deg, 3.0 gave -0.93 deg, 4.0 gave -1.10 deg
    # (worse again). Re-verify on hardware before trusting this value
    # there — docs/balance-controller.md §7 is explicit sim gains don't
    # transfer 1:1, and this one specifically gates how fast a correction
    # can reach the real servo bus.
    max_rate_rad_per_s: float = 3.0

    # Tilt smaller than this (rad) is treated as zero error, so the robot
    # doesn't micro-jitter (and wear the servos) while standing still and
    # already level.
    deadband_rad: float = 0.01


@dataclass(frozen=True)
class AttitudeReading:
    """Torso attitude and angular rate, from whatever sensor source is
    live (MuJoCo's framequat + gyro sensors in sim; the Pi's onboard IMU
    on hardware).

    Sign convention (matching this codebase's existing rule that
    left/right/forward are always the robot's own, not an observer's):
    positive pitch = leaning forward, positive roll = leaning toward the
    robot's own right. This is a design assumption, NOT yet verified
    against either MuJoCo's actual sensor output or the real IMU — confirm
    it before trusting this controller's correction direction. Getting
    this backwards means the controller actively pushes the robot over
    faster than doing nothing, which is worse than having no controller.
    """

    pitch_rad: float
    roll_rad: float
    pitch_rate: float
    roll_rate: float


# The four correction channels (docs/balance-controller.md §3): ankle
# roll/pitch and hip roll/pitch. Both legs move symmetrically for a given
# channel — this is a torso-level tilt correction, not an independent
# per-leg one.
_ANKLE_PITCH_JOINTS: tuple[str, ...] = ("l_ank_pitch", "r_ank_pitch")
_ANKLE_ROLL_JOINTS: tuple[str, ...] = ("l_ank_roll", "r_ank_roll")
_HIP_PITCH_JOINTS: tuple[str, ...] = ("l_hip_pitch", "r_hip_pitch")
_HIP_ROLL_JOINTS: tuple[str, ...] = ("l_hip_roll", "r_hip_roll")


def _apply_deadband(error: float, deadband: float) -> float:
    """Shrink error toward zero by `deadband`, continuously (no jump at
    the boundary) rather than a hard if/else cutoff."""
    if error > deadband:
        return error - deadband
    if error < -deadband:
        return error + deadband
    return 0.0


def _clamp_magnitude(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


class BalanceController:
    """Stateful two-tier PD controller. Call update() once per control tick."""

    def __init__(self, gains: BalanceGains | None = None):
        self.gains = gains if gains is not None else BalanceGains()
        self._prev = {"ankle_pitch": 0.0, "ankle_roll": 0.0, "hip_pitch": 0.0, "hip_roll": 0.0}

    def reset(self) -> None:
        """Zero all correction state. Call when the balance loop is
        paused/resumed or the robot is physically repositioned (e.g. after
        a fall recovery, or a manual reset command) — otherwise the rate
        limiter measures the jump from a stale previous offset instead of
        from the robot's actual current, uncorrected state."""
        for k in self._prev:
            self._prev[k] = 0.0

    def _rate_limit(self, channel: str, target: float, dt: float) -> float:
        prev = self._prev[channel]
        max_step = self.gains.max_rate_rad_per_s * max(dt, 0.0)
        delta = _clamp_magnitude(target - prev, max_step)
        new_value = prev + delta
        self._prev[channel] = new_value
        return new_value

    def update(self, attitude: AttitudeReading, dt: float) -> dict[str, float]:
        """Compute this tick's correction.

        Returns a joint-name -> radian OFFSET dict for exactly the eight
        joints in the four two-leg channels above — always meant to be
        ADDED to a baseline pose, never used as an absolute target on its
        own. This controller enforces its own per-channel safety cap
        (`max_correction_rad`), but has no idea what the baseline pose is,
        so it cannot guarantee the combined result stays within a joint's
        real range by itself — callers MUST run the result through
        `apply_balance_offset()` (or an equivalent real-limit clamp)
        before dispatch.
        """
        g = self.gains

        pitch_err = _apply_deadband(attitude.pitch_rad, g.deadband_rad)
        roll_err = _apply_deadband(attitude.roll_rad, g.deadband_rad)

        # Ankle strategy: PD term, negated so a positive tilt (leaning
        # forward/right) produces a correction opposing it.
        raw_ankle_pitch = -(g.ankle_kp * pitch_err + g.ankle_kd * attitude.pitch_rate)
        raw_ankle_roll = -(g.ankle_kp * roll_err + g.ankle_kd * attitude.roll_rate)

        ankle_pitch = _clamp_magnitude(raw_ankle_pitch, g.ankle_saturation_rad)
        ankle_roll = _clamp_magnitude(raw_ankle_roll, g.ankle_saturation_rad)

        # Hip strategy: only engages once the ankle term alone would have
        # exceeded its soft bound — a second, independent PD term on the
        # same error, not a scaled remainder of the ankle term.
        hip_pitch = 0.0
        hip_roll = 0.0
        if abs(raw_ankle_pitch) > g.ankle_saturation_rad:
            hip_pitch = -(g.hip_kp * pitch_err + g.hip_kd * attitude.pitch_rate)
        if abs(raw_ankle_roll) > g.ankle_saturation_rad:
            hip_roll = -(g.hip_kp * roll_err + g.hip_kd * attitude.roll_rate)

        # Hard safety cap, independent of (and here, looser than) the soft
        # ankle-saturation bound above — applies to every channel.
        ankle_pitch = _clamp_magnitude(ankle_pitch, g.max_correction_rad)
        ankle_roll = _clamp_magnitude(ankle_roll, g.max_correction_rad)
        hip_pitch = _clamp_magnitude(hip_pitch, g.max_correction_rad)
        hip_roll = _clamp_magnitude(hip_roll, g.max_correction_rad)

        ankle_pitch = self._rate_limit("ankle_pitch", ankle_pitch, dt)
        ankle_roll = self._rate_limit("ankle_roll", ankle_roll, dt)
        hip_pitch = self._rate_limit("hip_pitch", hip_pitch, dt)
        hip_roll = self._rate_limit("hip_roll", hip_roll, dt)

        offsets: dict[str, float] = {}
        for j in _ANKLE_PITCH_JOINTS:
            offsets[j] = ankle_pitch
        for j in _ANKLE_ROLL_JOINTS:
            offsets[j] = ankle_roll
        for j in _HIP_PITCH_JOINTS:
            offsets[j] = hip_pitch
        for j in _HIP_ROLL_JOINTS:
            offsets[j] = hip_roll
        return offsets


def apply_balance_offset(
    baseline_joints: dict[str, float],
    offset: dict[str, float],
    joint_limits: dict | None = None,
) -> dict[str, float]:
    """Add a balance offset on top of a baseline pose and clamp through
    real per-joint limits (`validation.JOINT_LIMITS` by default).

    This is the step that actually satisfies docs/balance-controller.md
    §4's "every corrective output is clamped... before being written to
    the servo bus" requirement — `BalanceController.update()` alone can't
    do this since it never sees the baseline pose. Joints present in
    `offset` but missing from `baseline_joints` are skipped (nothing to
    add the correction to).

    `joint_limits` defaults to `validation.JOINT_LIMITS`, imported lazily
    here (not at module load) so this module has no hard dependency on
    the `app` package layout — a caller that always passes its own
    `joint_limits` (e.g. the Pi-side balance loop, which builds one
    locally from HW_SERVO_LIMITS since it doesn't deploy the rest of the
    `app` package) never triggers this import at all.
    """
    if joint_limits is None:
        try:
            from app.validation import JOINT_LIMITS as limits
        except ImportError:
            from validation import JOINT_LIMITS as limits  # flat Pi deployment
    else:
        limits = joint_limits

    result = dict(baseline_joints)
    for joint, delta in offset.items():
        if joint not in baseline_joints:
            continue
        value = baseline_joints[joint] + delta
        limit = limits.get(joint)
        if limit is not None:
            value = limit.clamp(value)
        result[joint] = value
    return result
