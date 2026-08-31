"""Bridge the vision server's pose stream to robot motion.

Two voice-triggered actions:
- start_follow(): continuously mirror the human's arms + head until stop_follow()
- trigger_capture_and_mimic(): kick off the 3-second stability capture, then snap
  the robot to the frozen pose.

Status events ("follow_status", "capture_status") are pushed through a caller-
supplied async callback so the chat WebSocket layer stays in server.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional

import httpx
import websockets

from app.robot.interface import ServoCommand
from app.services.clean_logger import CleanLogger
from app.vision.pose_to_robot import (
    JointAngleSmoother,
    compute_joint_targets,
    targets_to_servo_commands,
)

logger = logging.getLogger("follow_controller")

VISION_HTTP_BASE = "http://localhost:8001"
VISION_WS_URL = "ws://localhost:8001/ws/pose"

# Follow loop tuning. duration_ms is kept slightly under one dispatch tick so
# each interpolation completes before the next command arrives — otherwise
# the blocking SimController.send_commands stacks up and adds latency.
_FOLLOW_DISPATCH_HZ = 20.0
_FOLLOW_DURATION_MS = 45
# One-shot easing from STAND to the human's first detected pose. Going at the
# fast loop's 45 ms straight to a fully extended arm would slam the joints in
# one tick; this slower opening move makes the start of follow mode smooth.
_FOLLOW_SEED_DURATION_MS = 800
_CAPTURE_DURATION_MS = 1500
_CAPTURE_TIMEOUT_S = 20.0

DispatchFn = Callable[[list[ServoCommand], bool | None], Awaitable[None]]
StatusFn = Callable[[dict], Awaitable[None]]


class FollowController:
    def __init__(self, dispatch_fn: DispatchFn):
        self._dispatch = dispatch_fn
        self._task: Optional[asyncio.Task] = None
        self._capture_task: Optional[asyncio.Task] = None

    @property
    def is_following(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def is_capturing(self) -> bool:
        return self._capture_task is not None and not self._capture_task.done()

    async def start_follow(
        self,
        status_fn: StatusFn,
        sim_only: bool | None = None,
        clean_logger: CleanLogger | None = None,
    ) -> None:
        if self.is_following:
            return
        # Reset any frozen stability capture so the vision stream goes live again.
        # Safe to call even when not frozen — the endpoint is a no-op in that case.
        try:
            async with httpx.AsyncClient(timeout=3.0) as http:
                await http.post(f"{VISION_HTTP_BASE}/capture/stable_position/continue")
        except Exception as e:
            logger.debug("Vision continue on follow-start failed: %s", e)
        self._task = asyncio.create_task(self._follow_loop(status_fn, sim_only, clean_logger))
        if clean_logger is not None:
            clean_logger.follow_started()

    async def stop_follow(
        self,
        status_fn: Optional[StatusFn] = None,
        reason: Optional[str] = None,
        clean_logger: CleanLogger | None = None,
    ) -> None:
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if status_fn is not None:
            await status_fn({"type": "follow_status", "active": False})
        if clean_logger is not None:
            clean_logger.follow_stopped(reason=reason)

    async def _follow_loop(
        self,
        status_fn: StatusFn,
        sim_only: bool | None = None,
        clean_logger: CleanLogger | None = None,
    ) -> None:
        """Split into reader + dispatcher so stale frames can't queue up.

        Sequence:
          1. Reader connects to vision WS, keeps only the freshest pose payload.
          2. Wait for the first frame that produces a non-empty target dict, do
             ONE long-duration ease from STAND to that pose so the start of
             follow mode isn't a 45 ms slam.
          3. Tick at _FOLLOW_DISPATCH_HZ, fire-and-forget; skip a tick if the
             previous dispatch hasn't finished.
        """
        smoother = JointAngleSmoother()
        latest: dict | None = None
        latest_event = asyncio.Event()

        try:
            await status_fn({"type": "follow_status", "active": True})
            async with websockets.connect(VISION_WS_URL, max_queue=8) as ws:

                async def reader() -> None:
                    nonlocal latest
                    try:
                        async for raw in ws:
                            try:
                                data = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            if not isinstance(data, dict):
                                continue
                            if data.get("type") not in (None, "pose_update"):
                                continue
                            latest = data
                            latest_event.set()
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.warning("Follow reader exited: %s", e)
                        if clean_logger is not None:
                            clean_logger.follow_error("vision reader exited", e)

                def _log_dispatch_error(t: asyncio.Task) -> None:
                    if t.cancelled():
                        return
                    exc = t.exception()
                    if exc is not None:
                        logger.warning("Follow dispatch error: %s", exc)

                reader_task = asyncio.create_task(reader())
                in_flight: Optional[asyncio.Task] = None
                dispatch_count = 0
                skip_count = 0
                empty_target_count = 0
                last_heartbeat = asyncio.get_event_loop().time()
                tick = 1.0 / _FOLLOW_DISPATCH_HZ
                try:
                    # ── Seed move: wait for the first usable pose, then ease there. ──
                    seeded = False
                    while not seeded:
                        await latest_event.wait()
                        data = latest
                        if data is None:
                            continue
                        body = data.get("body_landmarks") or []
                        head = data.get("head_pose")
                        targets = compute_joint_targets(body, head) if body else {}
                        if not targets:
                            # Person partly out of frame — try again on the next push.
                            latest_event.clear()
                            continue
                        targets = smoother.smooth(targets)
                        seed_cmds = targets_to_servo_commands(targets, _FOLLOW_SEED_DURATION_MS)
                        logger.info("Follow: seeding initial pose (%d joints)", len(seed_cmds))
                        if clean_logger is not None:
                            clean_logger.follow_event("seeding initial pose", {"joints": len(seed_cmds)})
                        await self._dispatch(seed_cmds, sim_only)
                        seeded = True
                    logger.info("Follow: initial seed complete, entering live tracking")
                    if clean_logger is not None:
                        clean_logger.follow_event("initial seed complete, live tracking")

                    # ── Live tracking loop. ──
                    while True:
                        await asyncio.sleep(tick)
                        data = latest
                        if data is None:
                            continue

                        body = data.get("body_landmarks") or []
                        head = data.get("head_pose")
                        targets = compute_joint_targets(body, head) if body else {}
                        if not targets:
                            empty_target_count += 1
                        else:
                            targets = smoother.smooth(targets)
                            if in_flight is not None and not in_flight.done():
                                skip_count += 1
                            else:
                                commands = targets_to_servo_commands(targets, _FOLLOW_DURATION_MS)
                                in_flight = asyncio.create_task(self._dispatch(commands, sim_only))
                                in_flight.add_done_callback(_log_dispatch_error)
                                dispatch_count += 1

                        # 2-second heartbeat: shows whether we're flowing.
                        now = asyncio.get_event_loop().time()
                        if now - last_heartbeat >= 2.0:
                            logger.info(
                                "Follow: %d dispatches, %d skips, %d empty-targets in last 2s",
                                dispatch_count, skip_count, empty_target_count,
                            )
                            if clean_logger is not None:
                                clean_logger.follow_tick(dispatch_count, skip_count, empty_target_count)
                            dispatch_count = skip_count = empty_target_count = 0
                            last_heartbeat = now
                finally:
                    reader_task.cancel()
                    if in_flight is not None and not in_flight.done():
                        in_flight.cancel()
        except asyncio.CancelledError:
            logger.info("Follow loop cancelled")
            if clean_logger is not None:
                clean_logger.follow_stopped(reason="cancelled")
            raise
        except Exception as exc:
            logger.warning("Follow loop error: %s", exc)
            if clean_logger is not None:
                clean_logger.follow_error("loop crashed", exc)
            await status_fn({"type": "follow_status", "active": False, "error": str(exc)})

    async def trigger_capture_and_mimic(
        self,
        status_fn: StatusFn,
        sim_only: bool | None = None,
        clean_logger: CleanLogger | None = None,
    ) -> None:
        if self.is_capturing:
            return
        self._capture_task = asyncio.create_task(self._capture_flow(status_fn, sim_only, clean_logger))
        if clean_logger is not None:
            clean_logger.capture_started()

    async def _capture_flow(
        self, status_fn: StatusFn, sim_only: bool | None = None, clean_logger: CleanLogger | None = None
    ) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                resp = await http.post(f"{VISION_HTTP_BASE}/capture/stable_position/start")
                resp.raise_for_status()

            await status_fn({"type": "capture_status", "stage": "started"})
            if clean_logger is not None:
                clean_logger.capture_stage("started")

            frozen_landmarks: list[dict] = []
            frozen_head: Optional[dict] = None
            async with websockets.connect(VISION_WS_URL, max_queue=8) as ws:
                async with asyncio.timeout(_CAPTURE_TIMEOUT_S):
                    while True:
                        raw = await ws.recv()
                        data = json.loads(raw)
                        stability = data.get("stability") or {}
                        state = stability.get("state")
                        if state == "countdown":
                            remaining = stability.get("countdown_remaining")
                            await status_fn({
                                "type": "capture_status",
                                "stage": "countdown",
                                "countdown_remaining": remaining,
                            })
                            if clean_logger is not None:
                                clean_logger.capture_stage("countdown", {"remaining": remaining})
                        elif state == "collecting":
                            progress = stability.get("collection_progress")
                            await status_fn({
                                "type": "capture_status",
                                "stage": "collecting",
                                "progress": progress,
                            })
                            if clean_logger is not None:
                                clean_logger.capture_stage("collecting", {"progress": progress})
                        elif state == "frozen":
                            frozen_landmarks = data.get("body_landmarks") or []
                            frozen_head = data.get("head_pose")
                            if clean_logger is not None:
                                clean_logger.capture_stage("frozen")
                            break

            if not frozen_landmarks:
                # Fallback: fetch the frozen frame via REST in case the WS didn't carry it
                async with httpx.AsyncClient(timeout=5.0) as http:
                    resp = await http.get(f"{VISION_HTTP_BASE}/capture/stable_position/frozen")
                    if resp.status_code == 200:
                        payload = resp.json()
                        frozen_landmarks = payload.get("body_landmarks") or []
                        frozen_head = payload.get("head_pose")

            await status_fn({"type": "capture_status", "stage": "frozen"})
            if clean_logger is not None:
                clean_logger.capture_stage("frozen")

            targets = compute_joint_targets(frozen_landmarks, frozen_head)
            commands = targets_to_servo_commands(targets, _CAPTURE_DURATION_MS)

            # Unfreeze the video feed before dispatching so the camera shows the live
            # view while the robot transitions to the captured pose.
            async with httpx.AsyncClient(timeout=5.0) as http:
                try:
                    await http.post(f"{VISION_HTTP_BASE}/capture/stable_position/continue")
                except Exception as e:
                    logger.debug("Vision continue post failed: %s", e)

            await self._dispatch(commands, sim_only)
            await status_fn({"type": "capture_status", "stage": "done"})
            if clean_logger is not None:
                clean_logger.capture_stage("done", {"joints": len(commands)})

        except asyncio.TimeoutError:
            logger.warning("Capture flow timed out waiting for frozen frame")
            if clean_logger is not None:
                clean_logger.capture_error("timeout waiting for frozen frame")
            await status_fn({"type": "capture_status", "stage": "error", "error": "timeout"})
        except Exception as exc:
            logger.warning("Capture flow error: %s", exc)
            if clean_logger is not None:
                clean_logger.capture_error("flow failed", exc)
            await status_fn({"type": "capture_status", "stage": "error", "error": str(exc)})
