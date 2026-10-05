"""Voice commands for the real robot's walking engine.

"march in place", "turn left", "take 3 steps forward", "walk backwards",
"stop walking". Each command walks for a short, fixed time, renewing the
walk every KEEPALIVE_S, then stops; a new command replaces the one running.
The robot's own dead-man timer (pi/nodes/walking.py) stops it if this
process goes away mid-walk.

"step back" is NOT a walk: it already means undo. "turn your head left" is
a head move; only "turn left" / "turn to the left" walk.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Union

from loguru import logger

# Engine settings for a voice walk: step length (m, engine limit 0.02) and
# turn per step (deg, engine limit 10; positive = robot's own left,
# confirmed on the robot 2026-10-05). The same 1 cm the walk test used.
STEP_M = 0.01
TURN_DEG = 8.0
MARCH_S = 4.0
TURN_S = 3.0
SECONDS_PER_STEP = 0.5
DEFAULT_STEPS = 3
MAX_STEPS = 6
KEEPALIVE_S = 0.3

STOP = "stop"

_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_STOP_RE = re.compile(r"\bstop\s+(walking|marching|stepping|moving your legs)\b", re.I)
_MARCH_RE = re.compile(r"\bmarch(ing)?\b", re.I)
_TURN_RE = re.compile(r"\b(turn|spin)\s+(?:to\s+(?:the|your)\s+)?(?P<dir>left|right)\b", re.I)
_FORWARD_RE = re.compile(r"\b(walk|step|steps)\s+(forwards?|ahead)\b", re.I)
_BACK_RE = re.compile(r"\b(walk\s+back(wards?)?|(walk|step|steps)\s+backwards?|steps\s+back)\b", re.I)
_COUNT_RE = re.compile(r"\b(?P<n>\d+|one|two|three|four|five|six)\s+steps?\b", re.I)


@dataclass(frozen=True)
class WalkCommand:
    forward: float
    turn: float
    seconds: float
    what: str  # for the spoken reply, e.g. "turning left"


WalkFn = Callable[..., Awaitable[None]]


def _steps(text: str) -> int:
    m = _COUNT_RE.search(text)
    if m is None:
        return DEFAULT_STEPS
    n = m.group("n").lower()
    count = _NUMBERS[n] if n in _NUMBERS else int(n)
    return max(1, min(MAX_STEPS, count))


def parse_walk_command(text: str) -> Union[WalkCommand, str, None]:
    """WalkCommand, STOP, or None when `text` isn't a walking command."""
    if _STOP_RE.search(text):
        return STOP
    if m := _TURN_RE.search(text):
        left = m.group("dir").lower() == "left"
        return WalkCommand(0.0, TURN_DEG if left else -TURN_DEG, TURN_S,
                           "turning left" if left else "turning right")
    for regex, sign, label in ((_FORWARD_RE, 1, "forward"), (_BACK_RE, -1, "backward")):
        if regex.search(text):
            n = _steps(text)
            return WalkCommand(sign * STEP_M, 0.0, n * SECONDS_PER_STEP,
                               f"taking {n} step{'s' if n != 1 else ''} {label}")
    if _MARCH_RE.search(text):
        return WalkCommand(0.0, 0.0, MARCH_S, "marching in place")
    return None


_task: Optional[asyncio.Task] = None


def _robot_walk() -> WalkFn:
    from app.services.motion import set_robot_walking

    return set_robot_walking


async def start_walk(cmd: WalkCommand, walk_fn: Optional[WalkFn] = None) -> None:
    """Start `cmd` in the background, replacing any walk in progress."""
    global _task
    walk_fn = walk_fn or _robot_walk()
    await _cancel()
    _task = asyncio.create_task(_run(cmd, walk_fn))


async def stop_walk(walk_fn: Optional[WalkFn] = None) -> None:
    await _cancel()
    await _send_stop(walk_fn or _robot_walk())


async def _cancel() -> None:
    global _task
    task, _task = _task, None
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _run(cmd: WalkCommand, walk_fn: WalkFn) -> None:
    loop = asyncio.get_running_loop()
    end = loop.time() + cmd.seconds
    try:
        while loop.time() < end:
            await walk_fn(True, forward=cmd.forward, turn=cmd.turn)
            await asyncio.sleep(KEEPALIVE_S)
    except asyncio.CancelledError:
        raise  # replaced by a new walk, or stop_walk sends the stop
    except Exception as e:
        logger.warning("Voice walk failed: {}", e)
    await _send_stop(walk_fn)


async def _send_stop(walk_fn: WalkFn) -> None:
    try:
        await walk_fn(False)
    except Exception as e:
        logger.warning("Voice walk stop failed: {}", e)
