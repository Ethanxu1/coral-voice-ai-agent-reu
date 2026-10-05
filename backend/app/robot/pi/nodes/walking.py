#!/usr/bin/env python3
"""Hiwonder's walking engine, driven by server.py's /walk endpoints.

The engine (ainex_controller: /walking/command, /walking/set_param,
/walking/get_param) marches in place, steps forward/back and turns --
confirmed on the robot 2026-10-05. It sends its own leg servo commands, so
while it walks (and while the legs settle back to stand afterwards) the
legs belong to it: `legs_busy` tells server.py to keep other leg targets
off the bus.

Dead-man timer: a walk only lasts while the laptop keeps re-sending /walk.
If nothing arrives for KEEPALIVE_TIMEOUT_S (Wi-Fi dropped, app crashed,
browser closed) the walk stops on its own. Without it a lost link would
leave the robot marching.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict

# Hiwonder's own tested ranges (ainex_kinematics/gait_manager.py).
FORWARD_MAX_M = 0.02
TURN_MAX_DEG = 10.0
# Lift 1-3 cm; gait_manager allows 4, kept lower until tried on the robot.
STEP_HEIGHT_M = (0.01, 0.03)
# One step cycle, share of it on both feet, side-to-side hip sway. Slightly
# slower than Hiwonder's 400 ms default -- what coral_walk_test.py ran.
PERIOD_MS = 500
DSP_RATIO = 0.2
Y_SWAP_M = 0.02
KEEPALIVE_TIMEOUT_S = 1.5
WATCH_PERIOD_S = 0.1
# Before standing: let the engine finish the step it is in.
STOP_SETTLE_S = 0.6
# Gap between publishing new settings and starting, so start uses them.
PARAMS_SETTLE_S = 0.1

# Leg servos the walk owns: ankles, knees, hips (ids 1-12).
LEG_SERVO_IDS = frozenset(range(1, 13))
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


class WalkerBusy(RuntimeError):
    """The legs are still settling back to stand after a walk."""


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
                 spawn: Callable[[Callable[[], None]], None] | None = None):
        self._engine = engine
        self._stand_legs = stand_legs
        self._clock = clock
        self._sleep = sleep
        self._spawn = spawn or (lambda f: threading.Thread(target=f, daemon=True).start())
        self._lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self.state = "idle"  # idle | walking | settling
        self._deadline = 0.0

    @property
    def legs_busy(self) -> bool:
        return self.state != "idle"

    def walk(self, forward: float = 0.0, turn: float = 0.0,
             step_height: float = 0.02) -> dict:
        """Start walking, or update a walk in progress and keep it alive."""
        settings = {
            "forward": _clamp(forward, -FORWARD_MAX_M, FORWARD_MAX_M),
            "turn": _clamp(turn, -TURN_MAX_DEG, TURN_MAX_DEG),
            "step_height": _clamp(step_height, *STEP_HEIGHT_M),
        }
        with self._lock:
            if self.state == "settling":
                raise WalkerBusy("legs are settling back to stand")
            p = self._engine.get_params()
            p.period_time = PERIOD_MS
            p.dsp_ratio = DSP_RATIO
            p.y_swap_amplitude = Y_SWAP_M
            p.x_move_amplitude = settings["forward"]
            p.y_move_amplitude = 0.0
            p.angle_move_amplitude = settings["turn"]
            p.z_move_amplitude = settings["step_height"]
            p.arm_swing_gain = 0.0  # arms stay with follow mode
            p.period_times = 0      # walk until stopped
            self._engine.set_params(p)
            if self.state == "idle":
                self._sleep(PARAMS_SETTLE_S)
                self._engine.command("start")
                self.state = "walking"
                self._idle.clear()
            self._deadline = self._clock() + KEEPALIVE_TIMEOUT_S
        return settings

    def stop(self) -> None:
        """Stop walking; the legs then ease back to stand in the background."""
        with self._lock:
            if self.state != "walking":
                return
            self._engine.command("stop")
            self.state = "settling"
        self._spawn(self._settle)

    def _settle(self) -> None:
        try:
            self._sleep(STOP_SETTLE_S)
            self._stand_legs()
        finally:
            with self._lock:
                self.state = "idle"
                self._idle.set()

    def wait_idle(self, timeout: float) -> bool:
        return self._idle.wait(timeout)

    def check_timeout(self) -> bool:
        """Stop a walk the laptop has stopped renewing. True if it did."""
        with self._lock:
            expired = self.state == "walking" and self._clock() > self._deadline
        if expired:
            self.stop()
        return expired

    def watch(self) -> None:
        """Dead-man timer loop; run in a daemon thread."""
        while True:
            self._sleep(WATCH_PERIOD_S)
            self.check_timeout()
