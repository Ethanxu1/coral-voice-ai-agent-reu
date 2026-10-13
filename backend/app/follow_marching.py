"""Follow mode's marching: when the person marches in place, the robot's own
walking engine marches in place too (pi/nodes/walking.py via POST /walk);
when they stop, it stops. It never turns (2026-10-13: "just keep the
marching at one place, remove any turning"); the robot side holds its
heading against its own drift with the gyro.

The robot does not copy each step -- the engine keeps its own rhythm and
balance. Follow mode keeps moving the arms; the robot ignores leg targets
while it marches. Never steps forward/back: the robot often stands on a desk.

The robot stops a march that isn't renewed, so this renews it every
KEEPALIVE_S, and sends an explicit stop at once when
the person stops or follow mode ends. One march lasts at most MAX_MARCH_S
(marching in place still drifts a little); after that the person has to
stop and start again.

With send=False (simulator: there is no walking engine) detection still runs
so the website can show it, but nothing is sent.

Marching only counts IN PLACE and IN VIEW (2026-10-12: walking toward the
camera started a march, and it kept marching after the person left the
frame): over the last MOVE_WINDOW_S the torso's size on screen must stay
within MAX_TORSO_CHANGE (walking toward/away changes it) and the hips within
MAX_HIP_SHIFT torso lengths (walking sideways); losing the body for
LOST_STOP_S stops it. While either holds, the detectors are reset.

Two detectors run side by side and either one starts a march: one on the 3D
thigh angle, one on the knee's height in the flat image (more reliable when
the camera misjudges depth). With a record_dir, every frame's readings and
the six points they come from (numbers only, no images) are saved as JSONL,
so a live run can be replayed exactly.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import IO, Awaitable, Callable, Optional

from loguru import logger

from app.vision.march_detector import RISE_DEG, MarchDetector, knee_lift_2d, thigh_raise_deg

# Renewal interval, s. The robot stops after 1.5 s without one; Wi-Fi round
# trips run ~0.1 s (worst seen 0.77 s, 2026-10-02).
KEEPALIVE_S = 0.3
# Matches pi/nodes/walking.py MAX_WALK_S: marching in place still creeps
# a little, so a march is capped (stop, then march again to continue).
MAX_MARCH_S = 20.0
# How often to log whether the legs are visible at all. 2026-10-12: a live
# test never marched because the camera framed hips and knees out of view
# (visibility ~0.03), and nothing said so.
VISIBILITY_LOG_S = 5.0

# From live recordings 2026-10-12: marching in place bobs the torso's size on
# screen by up to 23% and the hips by up to 0.28 torso lengths within 2 s;
# walking toward the camera grew it 40% within 1 s and moved the hips 0.4+.
MOVE_WINDOW_S = 2.0
MAX_TORSO_CHANGE = 0.35
MAX_HIP_SHIFT = 0.5
LOST_STOP_S = 0.5
_TORSO_IDX = (11, 12, 23, 24)

WalkFn = Callable[[bool], Awaitable[None]]


def _torso_on_screen(body: list[dict]) -> Optional[tuple[float, float, float]]:
    """(image torso length, hip-mid x, hip-mid y), or None if the shoulders
    and hips aren't all clearly seen."""
    if len(body) <= max(_TORSO_IDX):
        return None
    pts = [body[i] for i in _TORSO_IDX]
    if any(p.get("visibility", 0.0) < 0.5 or "x" not in p for p in pts):
        return None
    ls, rs, lh, rh = pts
    torso = (lh["y"] + rh["y"] - ls["y"] - rs["y"]) / 2
    if torso <= 0.02:
        return None
    return torso, (lh["x"] + rh["x"]) / 2, (lh["y"] + rh["y"]) / 2


class FollowMarching:
    def __init__(self, walk_fn: WalkFn, send: bool, record_dir: Optional[Path] = None) -> None:
        self._walk_fn = walk_fn
        self._send_enabled = send
        self._detector = MarchDetector()
        self._detector_2d = MarchDetector()
        self._window: deque = deque()
        self._lost_since: Optional[float] = None
        self._record: Optional[IO[str]] = None
        if record_dir is not None:
            record_dir.mkdir(parents=True, exist_ok=True)
            path = record_dir / f"{datetime.now():%Y%m%d_%H%M%S}.jsonl"
            self._record = path.open("w")
            logger.info("Follow: recording march readings to {}", path)
        self.marching = False
        self._capped = False
        self._march_start = 0.0
        self._last_sent = float("-inf")
        self._task: Optional[asyncio.Task] = None
        self._frames = 0
        self._legs_seen = 0
        self._peak = [0.0, 0.0]
        self._last_vis_log: Optional[float] = None

    def update(self, body: list[dict], now: float) -> bool:
        """Feed one camera frame (landmarks; [] if no person). Returns
        whether the robot should be marching. Never waits on the network."""
        l_deg, r_deg = thigh_raise_deg(body, "l"), thigh_raise_deg(body, "r")
        l_2d, r_2d = knee_lift_2d(body, "l"), knee_lift_2d(body, "r")
        self._peak = [max(self._peak[0], l_deg or 0.0), max(self._peak[1], r_deg or 0.0)]
        self._log_visibility(l_deg is not None and r_deg is not None, now)
        if self._in_place_and_in_view(body, now):
            by_3d = self._detector.update(l_deg, r_deg, now)
            by_2d = self._detector_2d.update(l_2d, r_2d, now)
        else:
            self._detector.reset()
            self._detector_2d.reset()
            by_3d = by_2d = False
        person_marching = by_3d or by_2d
        self._write_record(now, body, (l_deg, r_deg, l_2d, r_2d), by_3d, by_2d)
        if not person_marching:
            self._capped = False
        marching = person_marching and not self._capped
        if marching and not self.marching:
            self._march_start = now
        if marching and now - self._march_start > MAX_MARCH_S:
            logger.info("Follow: march time limit reached; stop and march again to continue")
            self._capped = True
            marching = False
        if marching:
            due = now - self._last_sent >= KEEPALIVE_S
            if due and (self._task is None or self._task.done()):
                self._task = self._spawn(self._send(True))
                self._last_sent = now
        elif self.marching:
            # Stop at once -- don't wait for a renewal still on its way: one
            # arriving after the stop is refused (the robot is already
            # settling), so this can't restart the march (2026-10-13).
            self._task = self._spawn(self._send(False))
            self._last_sent = float("-inf")
        if marching != self.marching:
            logger.info("Follow: person {} marching", "started" if marching else "stopped")
        self.marching = marching
        return marching

    def _in_place_and_in_view(self, body: list[dict], now: float) -> bool:
        seen = _torso_on_screen(body)
        if seen is None:
            if self._lost_since is None:
                self._lost_since = now
            return now - self._lost_since <= LOST_STOP_S
        self._lost_since = None
        self._window.append((now, *seen))
        while self._window and now - self._window[0][0] > MOVE_WINDOW_S:
            self._window.popleft()
        torsos = [w[1] for w in self._window]
        xs, ys = [w[2] for w in self._window], [w[3] for w in self._window]
        mean_torso = sum(torsos) / len(torsos)
        grew = max(torsos) / min(torsos) - 1 > MAX_TORSO_CHANGE
        shifted = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) > MAX_HIP_SHIFT * mean_torso
        return not (grew or shifted)

    def _log_visibility(self, both_legs_seen: bool, now: float) -> None:
        self._frames += 1
        self._legs_seen += both_legs_seen
        if self._last_vis_log is None:
            self._last_vis_log = now
        elif now - self._last_vis_log >= VISIBILITY_LOG_S:
            share = self._legs_seen / self._frames
            if share < 0.5:
                logger.warning(
                    "Follow: hips/knees visible in only {:.0%} of frames -- marching can't be "
                    "detected. Step back so the camera sees you from the shoulders to the knees.",
                    share)
            else:
                logger.info("Follow: legs visible in {:.0%} of frames; highest thigh raise "
                            "L {:.0f} / R {:.0f} deg (a step is a rise of {:.0f} above rest)",
                            share, self._peak[0], self._peak[1], RISE_DEG)
            self._frames = self._legs_seen = 0
            self._peak = [0.0, 0.0]
            self._last_vis_log = now

    def status(self) -> dict:
        return {"marching": self.marching, "robot_only": not self._send_enabled}

    def _write_record(self, now, body, readings, by_3d, by_2d) -> None:
        if self._record is None:
            return
        pts = {i: [round(body[i].get(k, 0.0), 4) for k in ("x", "y", "xw", "yw", "zw", "visibility")]
               for i in (11, 12, 23, 24, 25, 26, 27, 28) if len(body) > i}
        self._record.write(json.dumps({
            "t": round(now, 3),
            "read": [None if v is None else round(v, 2) for v in readings],
            "by_3d": by_3d, "by_2d": by_2d, "marching": self.marching, "pts": pts,
        }) + "\n")

    async def close(self) -> None:
        """Follow mode is ending: make sure the robot isn't left marching."""
        if self._record is not None:
            self._record.close()
            self._record = None
        if self.marching:
            self.marching = False
            await self._send(False)
        elif self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)

    def _spawn(self, coro) -> Optional[asyncio.Task]:
        if not self._send_enabled:
            coro.close()
            return None
        return asyncio.create_task(coro)

    async def _send(self, walking: bool) -> None:
        if not self._send_enabled:
            return
        try:
            await self._walk_fn(walking)
        except Exception as e:
            logger.warning("Follow: march {} failed: {}", "renewal" if walking else "stop", e)
