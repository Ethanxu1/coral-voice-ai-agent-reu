"""The website's "Walk forward" / "Walk backward" / "Stop" buttons.

Each click walks the real robot for BUTTON_WALK_S with Hiwonder's walking
engine (pi/nodes/walking.py), renewing the walk every KEEPALIVE_S -- the
robot stops a walk that isn't renewed -- and then stops it. A new click
replaces the walk in progress without stopping in between; stop() ends it at
once. The robot side estimates how far it has walked from its start and
won't step past walking.MAX_TRAVEL_M either way, so it can't walk off a desk;
travel_message() tells the website where it stands, so a click at the limit
doesn't look like the robot ignoring it.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from loguru import logger

# One click: about 8 step cycles at the engine's 0.5 s period. 2 s of 1 cm
# steps couldn't be told apart from marching in place (2026-10-26).
BUTTON_WALK_S = 4.0
KEEPALIVE_S = 0.3
# pi/nodes/walking.py HEADING_KEEP_S: standing this long resets the travel.
TRAVEL_RESET_S = 30
CM_PER_M = 100

WalkFn = Callable[..., Awaitable[None]]


def _robot_walk() -> WalkFn:
    from app.services.motion import set_robot_walking

    return set_robot_walking


async def robot_walk_status() -> dict:
    from app.services.motion import robot_walk_status as read

    return await read()


def travel_message(status: dict, direction: int) -> Optional[str]:
    """How far the robot has walked toward ``direction`` (+1 forward, -1
    backward), or what to do at its travel limit. None without a status."""
    travel, limit = status.get("travel_m"), status.get("max_travel_m")
    if travel is None or limit is None:
        return None
    way, other = ("forward", "backward") if direction > 0 else ("backward", "forward")
    if direction * travel >= limit:
        return (f"Reached the {round(limit * CM_PER_M)} cm {way} limit, so it marches in place. "
                f"Use Walk {other}, or let it stand {TRAVEL_RESET_S} s to reset.")
    return f"Walked {round(abs(travel) * CM_PER_M)} of {round(limit * CM_PER_M)} cm {way} so far."


class WalkButtons:
    def __init__(self, walk_fn: Optional[WalkFn] = None) -> None:
        self._walk_fn = walk_fn
        self._task: Optional[asyncio.Task] = None

    @property
    def walking(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, direction: int) -> None:
        """Walk forward (+1) or backward (-1) for BUTTON_WALK_S."""
        await self._cancel()
        self._task = asyncio.create_task(self._run(direction))

    async def stop(self) -> None:
        await self._cancel()
        await self._send(False, 0)

    async def _cancel(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self, direction: int) -> None:
        loop = asyncio.get_running_loop()
        end = loop.time() + BUTTON_WALK_S
        try:
            while loop.time() < end:
                await self._send(True, direction)
                await asyncio.sleep(KEEPALIVE_S)
        except asyncio.CancelledError:
            raise  # replaced by a new click, or stop() sends the stop
        await self._send(False, 0)

    async def _send(self, walking: bool, direction: int) -> None:
        walk_fn = self._walk_fn or _robot_walk()
        try:
            await walk_fn(walking, direction)
        except Exception as e:
            logger.warning("Walk button: {} failed: {}", "walk" if walking else "stop", e)


buttons = WalkButtons()
