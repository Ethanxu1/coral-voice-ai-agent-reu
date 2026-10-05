"""Follow mode's marching: when the person marches, the robot's own walking
engine marches (pi/nodes/walking.py via POST /walk); when they stop, it stops.

The robot does not copy each step -- the engine keeps its own rhythm and
balance. While marching, follow mode keeps streaming the arms; the robot
ignores leg targets until the walk has ended and the legs have settled.

The robot stops a walk that isn't renewed, so this renews it every
KEEPALIVE_S while the person marches, and sends an explicit stop when they
stop or follow mode ends.

Turning: while marching, a torso turned past TURN_START_DEG turns the robot
TURN_STEP_DEG per step until the turn eases back under TURN_STOP_DEG. Sides
follow the landmarks' left/right labels -- the ones the arms copy -- so the
robot turns the way it would if it mirrored the arms. The camera image is
mirrored before pose detection, so for a person facing the robot that is a
reflection: they turn to their right, the robot turns to its left.
"""

from __future__ import annotations

import asyncio
import math
from typing import Awaitable, Callable, Optional

from loguru import logger

from app.vision.leg_lift_controller import signed_lift
from app.vision.march_detector import MarchDetector

# Renewal interval, s. The robot stops after 1.5 s without one; Wi-Fi round
# trips run ~0.1 s (worst seen 0.77 s, 2026-10-02).
KEEPALIVE_S = 0.3

# Torso turn, degrees: start / stop turning (hysteresis), and the robot's
# turn per step (engine limit 10; positive = robot's own left, confirmed on
# the robot 2026-10-05).
TURN_START_DEG = 25.0
TURN_STOP_DEG = 15.0
TURN_STEP_DEG = 8.0
# Low-pass on the torso reading, s: a turn is held, jitter is not.
TURN_TAU = 0.3
_MIN_VISIBILITY = 0.5
_L_SHOULDER, _R_SHOULDER = 11, 12

WalkFn = Callable[[bool, float], Awaitable[None]]


def torso_turn_deg(body: list[dict]) -> Optional[float]:
    """How far the shoulder line is turned toward the landmarks' LEFT side,
    degrees (the left shoulder swung back, away from the camera; MediaPipe
    world z grows away from it). None if either shoulder isn't seen."""
    if len(body) <= _R_SHOULDER:
        return None
    l, r = body[_L_SHOULDER], body[_R_SHOULDER]
    if min(l.get("visibility", 0.0), r.get("visibility", 0.0)) < _MIN_VISIBILITY:
        return None
    dx = abs(l["xw"] - r["xw"])
    dz = l["zw"] - r["zw"]
    return math.degrees(math.atan2(dz, dx))


def _lift(side: str, targets: dict[str, float]) -> Optional[float]:
    return signed_lift(side, targets) if f"{side}_hip_pitch" in targets else None


class FollowWalking:
    def __init__(self, walk_fn: WalkFn) -> None:
        self._walk_fn = walk_fn
        self._detector = MarchDetector()
        self.marching = False
        self._last_sent = float("-inf")
        self._task: Optional[asyncio.Task] = None
        self.turn = 0.0
        self._sent_turn = 0.0
        self._yaw = 0.0
        self._last_t: Optional[float] = None

    def update(self, targets: dict[str, float], now: float,
               body: Optional[list[dict]] = None) -> bool:
        """Feed one frame: retargeted targets ({} if no person) and the raw
        landmarks (for turning). Returns whether the robot should be
        marching. Never waits on the network."""
        dt = 0.0 if self._last_t is None else max(0.0, now - self._last_t)
        self._last_t = now
        marching = self._detector.update(_lift("l", targets), _lift("r", targets), now)
        self._update_turn(torso_turn_deg(body or []), dt, marching)
        due = now - self._last_sent >= KEEPALIVE_S or self.turn != self._sent_turn
        if marching and due:
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._send(True, self.turn))
                self._last_sent = now
                self._sent_turn = self.turn
        elif not marching and self.marching:
            self._task = asyncio.create_task(self._stop_after(self._task))
            self._last_sent = float("-inf")
        if marching != self.marching:
            logger.info("Follow: person {} marching", "started" if marching else "stopped")
        self.marching = marching
        return marching

    def _update_turn(self, yaw: Optional[float], dt: float, marching: bool) -> None:
        if yaw is not None:
            alpha = dt / (TURN_TAU + dt) if dt > 0 else 1.0
            self._yaw += alpha * (yaw - self._yaw)
        if not marching:
            turn = 0.0
        elif abs(self._yaw) >= TURN_START_DEG:
            turn = math.copysign(TURN_STEP_DEG, self._yaw)
        elif abs(self._yaw) <= TURN_STOP_DEG:
            turn = 0.0
        else:
            turn = self.turn
        if turn != self.turn and marching:
            logger.info("Follow: march turning {}", "left" if turn > 0 else
                        "right" if turn < 0 else "straight")
        self.turn = turn

    async def close(self) -> None:
        """Follow mode is ending: make sure the robot isn't left walking."""
        if self.marching:
            self.marching = False
            await self._stop_after(self._task)
        elif self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)

    async def _stop_after(self, previous: Optional[asyncio.Task]) -> None:
        if previous is not None and not previous.done():
            await asyncio.gather(previous, return_exceptions=True)
        await self._send(False)

    async def _send(self, walking: bool, turn: float = 0.0) -> None:
        try:
            await self._walk_fn(walking, turn)
        except Exception as e:
            logger.warning("Follow: walk {} failed: {}", "renewal" if walking else "stop", e)
