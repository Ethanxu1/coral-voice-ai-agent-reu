#!/usr/bin/env python3
"""Hiwonder's walking engine, driven by server.py's /walk endpoints.

The engine (ainex_controller: /walking/command, /walking/set_param,
/walking/get_param) marches in place -- confirmed on the robot 2026-10-05.
Only marching in place is exposed (2026-10-13: "just keep the marching at
one place, remove any turning"): forward/backward/sideways steps are always
0 (the robot often stands on a desk) and no turn is ever commanded. The only
turn setting is the gyro heading hold below, which steers AGAINST the
robot's own drift so that it keeps facing the same way.

It sends its own leg servo commands, and swings the arms in time with the
steps (ARM_SWING_DEG, like a person marching), so while it walks (and while
the legs settle back to stand afterwards) the body belongs to it:
`legs_busy` tells server.py to keep other leg and arm targets off the bus.

Safety stops:
- Dead-man timer: a walk lasts only while the laptop keeps re-sending /walk.
  Nothing for KEEPALIVE_TIMEOUT_S (Wi-Fi dropped, app crashed) -> stop.
- MAX_WALK_S: marching "in place" still creeps (feet slip; the engine plays
  its step pattern without sensing where the feet land) -- seen slightly
  forward on a table 2026-10-12 -- so one march is capped; after the cap
  only an explicit stop() re-arms walk(). X_TRIM_M can cancel a measured
  creep with a tiny opposite step, bounded by MAX_TRIM_M so it can never
  become walking.

Runs on the robot's Python 3.8.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Callable, Dict, Optional

# Hiwonder's own tested ranges (ainex_kinematics/gait_manager.py); bounds
# the heading-hold correction.
TURN_MAX_DEG = 10.0
# Foot lift 1-3 cm; gait_manager allows 4, kept lower until tried.
STEP_HEIGHT_M = (0.01, 0.03)
# One step cycle, share of it on both feet, side-to-side hip sway -- what
# coral_walk_test.py ran on the robot. Each foot is off the floor for
# PERIOD_MS * (1 - DSP_RATIO) / 2 = 200 ms per step.
PERIOD_MS = 500
DSP_RATIO = 0.2
Y_SWAP_M = 0.02
# Arm swing while marching, deg (gait_manager's default; 0 = arms untouched).
ARM_SWING_DEG = 30.0
KEEPALIVE_TIMEOUT_S = 1.5
MAX_WALK_S = 20.0
# Creep correction, m per step (negative = backward). Measured 2026-10-12:
# uncorrected ~2 mm/step forward; with -1.5 mm, 4 s -> 2 cm and 16 s ->
# 3-4 cm, i.e. ~1.5 cm per start/stop (engine crouch in/out, not
# correctable here) + ~0.6 mm/step still forward. Re-measure with the same
# short/long /walk loops after any change.
X_TRIM_M = -0.002
MAX_TRIM_M = 0.005
# Walking forward/backward (2026-10-26, website buttons): a direction of +1
# or -1 adds WALK_STEP_M per step. The robot can't see the desk edge, so it
# estimates how far it has walked from its start (travel_m, from the
# commanded steps -- an overestimate is the safe side) and stops stepping at
# MAX_TRAVEL_M either way; it keeps marching in place there. Reset like the
# heading, after HEADING_KEEP_S standing.
# 1 cm steps, arms still while stepping: what coral_walk_test.py walked
# stably with on the robot (2026-10-12). 2 cm steps with 30 deg arm swing
# were very wobbly (2026-10-26). The button walks 4 s so it shows.
WALK_STEP_M = 0.01
MAX_TRAVEL_M = 0.20
# Careful gait while stepping forward/back (2026-10-26: still wobbly "like
# it might fall" with 1 cm steps and arms still): Hiwonder's slowest cycle,
# more of each step on both feet, lower foot lift. Marching in place keeps
# PERIOD_MS / DSP_RATIO / its step height -- it is stable.
WALK_PERIOD_MS = 600
WALK_DSP_RATIO = 0.3
WALK_STEP_HEIGHT_M = 0.015
# Side-to-side hip sway while stepping. At 2 cm (and the slower cycle) it
# "kinda rocks side to side" (2026-10-26) -- overshoot; less sway. If it
# instead starts leaning toward the lifted foot, this is too small.
WALK_Y_SWAP_M = 0.015
# Heading hold while stepping: walking rocks the body, and chasing every
# rock turned the robot about at random over repeated clicks (2026-10-26).
# Errors within WALK_HOLD_DEADBAND_DEG are ignored, the correction is capped
# at WALK_HOLD_MAX_DEG per step, and it has no integral term.
WALK_HOLD_DEADBAND_DEG = 3.0
WALK_HOLD_MAX_DEG = 2.0
# Engine step cycles per second while stepping, one WALK_STEP_M per cycle,
# for the travel estimate. NOT measured yet: time a 4 s click and measure
# the distance, then compare with 4 s x STEPS_PER_S x WALK_STEP_M.
STEPS_PER_S = 1000.0 / WALK_PERIOD_MS
# Heading hold. Marching in place the robot turned ~30-45 deg to its right
# in 16 s (2026-10-12), with or without arm swing -- its own drift, which
# changes with surface and battery, so a fixed trim can't follow it. The
# onboard gyro measures the turning, and the march steers back toward the
# heading it started with:
#   hold = clamp(HOLD_GAIN x error + HOLD_INTEGRAL_GAIN x integral, +-HOLD_MAX_DEG)
# deg/step. The gyro's resting offset is learned only while the robot is
# truly still (BIAS_TAU_S, BIAS_MAX_DEG_S, BIAS_QUIET_S).
# Gyro axis: values 3-5 of Board().get_imu() are gyro x, y, z (deg/s); "up"
# is the accelerometer's Y on this robot, so turning should be gyro Y.
# YAW_GYRO_SIGN makes positive = turning to the robot's own left.
# CONFIRMED 2026-10-12 (scripts/gyro_check.py, hand turn to the robot's
# left): gyro x +0, gyro y +65, gyro z +4 -> axis 1 (y), sign +1.
YAW_GYRO_AXIS = 1
YAW_GYRO_SIGN = 1.0
HOLD_GAIN = 0.3
# Integral term (1/s): the proportional term alone leaves a steady offset
# when the robot keeps drifting (~4 deg at 1.2 deg/step), which adds up over
# a long march (2026-10-13: slow right turn on longer marches).
HOLD_INTEGRAL_GAIN = 0.15
HOLD_MAX_DEG = 4.0
# Keep the heading reference between marches for this long, so stopping and
# starting again doesn't make "wherever it faces now" the new straight ahead
# (small turns at each start/stop added up). Longer idle: start afresh.
HEADING_KEEP_S = 30.0
BIAS_TAU_S = 2.0
# A still robot's gyro reads near its small resting offset; readings above
# this (deg/s) mean it is moving (follow mode moves the arms before a march,
# twisting the body) and are not used to learn the offset.
BIAS_MAX_DEG_S = 3.0
# ...and not until this long after the last body command (/move): follow
# mode keeps moving the arms, and even slow movement twists the body; an
# offset learned from that made the hold steer the robot slowly sideways
# (2026-10-13).
BIAS_QUIET_S = 1.0
MAX_SENSE_DT_S = 0.2
WATCH_PERIOD_S = 0.02
# Before standing: let the engine finish its step. With an engine that
# reports /walking/is_walking, wait for it (up to STOP_WAIT_MAX_S) and record
# how long it took (last_stop_s); otherwise wait STOP_SETTLE_S.
STOP_SETTLE_S = 0.6
STOP_WAIT_MAX_S = 3.0
STOP_POLL_S = 0.05
# Gap between publishing new settings and starting, so start uses them.
PARAMS_SETTLE_S = 0.1

# Leg stand pulses -- mirrors body._STAND_PULSE (stand.d6a).
LEG_STAND_PULSE: Dict[str, int] = {
    "l_ank_roll": 500, "r_ank_roll": 500,
    "l_ank_pitch": 640, "r_ank_pitch": 360,
    "l_knee": 500, "r_knee": 500,
    "l_hip_pitch": 350, "r_hip_pitch": 650,
    "l_hip_roll": 500, "r_hip_roll": 500,
    "l_hip_yaw": 500, "r_hip_yaw": 500,
}
STAND_MS = 800


def yaw_rate_from_imu(values) -> Optional[float]:
    """Turning rate, deg/s, positive = toward the robot's own left, from
    Board().get_imu()'s 9 floats; None if the board didn't answer."""
    if not values or len(values) < 6:
        return None
    return YAW_GYRO_SIGN * float(values[3 + YAW_GYRO_AXIS])


# Board().get_imu() hands each reading out once (it reads a queue; None
# when empty). With more than one caller each steals the others' readings --
# live 2026-10-12, /imu only ever saw None once the heading hold polled it.
# So one LatestImu thread drains it and everyone reads the latest copy.
IMU_POLL_S = 0.005
IMU_STALE_S = 0.5


class LatestImu:
    def __init__(self, read: Callable[[], Optional[list]],
                 clock: Callable[[], float] = time.monotonic):
        self._read = read
        self._clock = clock
        self._values: Optional[list] = None
        self._at = 0.0
        self._lock = threading.Lock()

    def poll_once(self) -> None:
        values = self._read()
        if values is not None:
            with self._lock:
                self._values, self._at = list(values), self._clock()

    def latest(self) -> Optional[list]:
        """The newest reading, or None if there is none fresher than IMU_STALE_S."""
        with self._lock:
            if self._values is None or self._clock() - self._at > IMU_STALE_S:
                return None
            return list(self._values)

    def run(self) -> None:
        """Drain the board forever; run in a daemon thread."""
        while True:
            self.poll_once()
            time.sleep(IMU_POLL_S)


class WalkerBusy(RuntimeError):
    """Legs settling back to stand, or a capped march not yet stopped."""


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


class RosWalkingEngine:
    """The engine's ROS interface, in the shape Walker uses."""

    def __init__(self):
        import rospy
        from ainex_interfaces.msg import WalkingParam
        from ainex_interfaces.srv import GetWalkingParam, SetWalkingCommand

        rospy.wait_for_service("walking/command", timeout=5.0)
        self._get = rospy.ServiceProxy("walking/get_param", GetWalkingParam)
        self._pub = rospy.Publisher("walking/set_param", WalkingParam, queue_size=1)
        self._cmd = rospy.ServiceProxy("walking/command", SetWalkingCommand)
        from std_msgs.msg import Bool

        self._walking: Optional[bool] = None
        rospy.Subscriber("walking/is_walking", Bool, self._on_walking, queue_size=1)

    def _on_walking(self, msg) -> None:
        self._walking = bool(msg.data)

    def is_walking(self) -> Optional[bool]:
        """The engine's own report; None until it has said anything."""
        return self._walking

    def get_params(self):
        return self._get().parameters

    def set_params(self, msg) -> None:
        self._pub.publish(msg)

    def command(self, name: str) -> None:
        self._cmd(name)


class Walker:
    def __init__(self, engine, stand_legs: Callable[[], None],
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 spawn: Optional[Callable[[Callable[[], None]], None]] = None,
                 yaw_rate: Optional[Callable[[], Optional[float]]] = None):
        self._engine = engine
        self._yaw_rate = yaw_rate
        self.yaw_deg = 0.0          # turned since the march started, + = left
        self._target = 0.0
        self._bias: Optional[float] = None
        self._last_sense: Optional[float] = None
        self._body_moved_at: Optional[float] = None
        self.travel_m = 0.0          # estimated distance walked from the start, + = forward
        self._stepping_gait = False
        self._step_m = 0.0           # forward step being commanded now (no trim)
        self._integral = 0.0
        self._last_hold: Optional[float] = None
        self._idle_since: Optional[float] = None
        self.last_stop_s: Optional[float] = None
        self._stand_legs = stand_legs
        self._clock = clock
        self._sleep = sleep
        self._spawn = spawn or (lambda f: threading.Thread(target=f, daemon=True).start())
        self._lock = threading.Lock()
        self.state = "idle"  # idle | walking | settling
        self._deadline = 0.0
        self._started = 0.0
        self._capped = False

    @property
    def legs_busy(self) -> bool:
        return self.state != "idle"

    def note_body_motion(self) -> None:
        """A body command (/move) just played: the robot isn't still."""
        with self._lock:
            self._body_moved_at = self._clock()

    def walk(self, step_height: float = 0.02, direction: int = 0) -> dict:
        """Start marching (in place, or forward/backward with direction
        +1/-1), or renew a march in progress."""
        settings = {
            "step_height": _clamp(step_height, *STEP_HEIGHT_M),
            # Reported so a /walk reply shows which correction is deployed.
            "x_trim_m": _clamp(X_TRIM_M, -MAX_TRIM_M, MAX_TRIM_M),
        }
        direction = (direction > 0) - (direction < 0)
        # The gait follows what was ASKED, not whether the travel limit lets
        # it step: flipping to the marching gait mid-walk was a jolt.
        self._stepping_gait = direction != 0
        with self._lock:
            if self.state == "settling":
                raise WalkerBusy("legs are settling back to stand")
            if self._capped:
                raise WalkerBusy("march time limit reached; stop before marching again")
            p = self._engine.get_params()
            p.y_move_amplitude = 0.0
            if self.state == "idle" and (self._idle_since is None
                                         or self._clock() - self._idle_since > HEADING_KEEP_S):
                self.yaw_deg = self._target = 0.0
                self.travel_m = 0.0
            if self.state == "idle":
                self._integral = 0.0         # no steering left over from the last walk
            if direction * self.travel_m >= MAX_TRAVEL_M:
                direction = 0            # at the travel limit that way: march in place
            self._step_m = direction * WALK_STEP_M
            settings["direction"] = direction
            settings["travel_m"] = round(self.travel_m, 3)
            # Only the requested direction's small step, plus the creep trim.
            p.x_move_amplitude = settings["x_trim_m"] + self._step_m
            stepping = self._stepping_gait
            p.period_time = WALK_PERIOD_MS if stepping else PERIOD_MS
            p.dsp_ratio = WALK_DSP_RATIO if stepping else DSP_RATIO
            p.y_swap_amplitude = WALK_Y_SWAP_M if stepping else Y_SWAP_M
            p.angle_move_amplitude = _clamp(self._hold(), -TURN_MAX_DEG, TURN_MAX_DEG)
            p.z_move_amplitude = (min(settings["step_height"], WALK_STEP_HEIGHT_M)
                                  if stepping else settings["step_height"])
            # Arms swing only when marching in place; still while stepping.
            p.arm_swing_gain = 0.0 if stepping else math.radians(ARM_SWING_DEG)
            p.period_times = 0         # walk until stopped
            self._engine.set_params(p)
            if self.state == "idle":
                self._sleep(PARAMS_SETTLE_S)
                self._engine.command("start")
                self.state = "walking"
                self._started = self._clock()
            self._deadline = self._clock() + KEEPALIVE_TIMEOUT_S
        return settings

    def _hold(self) -> float:
        """Heading-hold correction, deg/step (caller holds the lock)."""
        now = self._clock()
        dt = 0.0 if self._last_hold is None else min(0.5, now - self._last_hold)
        self._last_hold = now
        if self._yaw_rate is None:
            return 0.0
        error = self._target - self.yaw_deg
        if self._stepping_gait:
            beyond = abs(error) - WALK_HOLD_DEADBAND_DEG
            if beyond <= 0:
                return 0.0
            return math.copysign(min(WALK_HOLD_MAX_DEG, HOLD_GAIN * beyond), error)
        limit = HOLD_MAX_DEG / HOLD_INTEGRAL_GAIN
        self._integral = _clamp(self._integral + error * dt, -limit, limit)
        return _clamp(HOLD_GAIN * error + HOLD_INTEGRAL_GAIN * self._integral,
                      -HOLD_MAX_DEG, HOLD_MAX_DEG)

    def sense(self) -> None:
        """Read the gyro: learn its bias while standing, integrate the
        heading while marching. Called from watch()."""
        now = self._clock()
        dt = 0.0 if self._last_sense is None else min(MAX_SENSE_DT_S, now - self._last_sense)
        self._last_sense = now
        with self._lock:
            if self.state == "walking":
                self.travel_m += self._step_m * STEPS_PER_S * dt
        if self._yaw_rate is None:
            return
        rate = self._yaw_rate()
        if rate is None:
            return
        with self._lock:
            quiet = self._body_moved_at is None or now - self._body_moved_at >= BIAS_QUIET_S
            if self.state == "idle" and quiet and abs(rate) <= BIAS_MAX_DEG_S:   # still only
                if self._bias is None:
                    self._bias = rate
                else:
                    self._bias += dt / (BIAS_TAU_S + dt) * (rate - self._bias)
            elif self.state != "idle":          # walking or settling back to stand
                self.yaw_deg += (rate - (self._bias or 0.0)) * dt

    def stop(self) -> None:
        """Stop walking (legs ease back to stand in the background); also
        re-arms walk() after a capped march."""
        with self._lock:
            self._capped = False
            if self.state != "walking":
                return
            self._engine.command("stop")
            self.state = "settling"
            self._step_m = 0.0
        self._spawn(self._settle)

    def _settle(self) -> None:
        try:
            self._wait_for_engine_stop()
            self._stand_legs()
        finally:
            with self._lock:
                self.state = "idle"
                self._idle_since = self._clock()

    def _wait_for_engine_stop(self) -> None:
        report = getattr(self._engine, "is_walking", None)
        start = self._clock()
        if report is None or report() is None:
            self._sleep(STOP_SETTLE_S)
            return
        while report() and self._clock() - start < STOP_WAIT_MAX_S:
            self._sleep(STOP_POLL_S)
        self.last_stop_s = round(self._clock() - start, 2)

    def check_timeout(self) -> bool:
        """Stop a walk the laptop stopped renewing, or one past MAX_WALK_S.
        True if it stopped one."""
        with self._lock:
            if self.state != "walking":
                return False
            now = self._clock()
            capped = now - self._started > MAX_WALK_S
            expired = capped or now > self._deadline
        if expired:
            self.stop()
            if capped:
                with self._lock:
                    self._capped = True
        return expired

    def watch(self) -> None:
        """Safety-stop loop; run in a daemon thread."""
        while True:
            self._sleep(WATCH_PERIOD_S)
            self.sense()
            self.check_timeout()
