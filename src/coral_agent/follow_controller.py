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

from coral_agent.robot.interface import ServoCommand
from coral_agent.vision.pose_to_robot import (
    PoseTargetSmoother,
    compute_joint_targets,
    targets_to_servo_commands,
)

logger = logging.getLogger("follow_controller")

VISION_HTTP_BASE = "http://localhost:8001"
VISION_WS_URL = "ws://localhost:8001/ws/pose"

# Follow loop tuning
_FOLLOW_DISPATCH_HZ = 15.0
_FOLLOW_DURATION_MS = 100
_CAPTURE_DURATION_MS = 1500
_CAPTURE_TIMEOUT_S = 20.0

DispatchFn = Callable[[list[ServoCommand]], Awaitable[None]]
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

    async def start_follow(self, status_fn: StatusFn) -> None:
        if self.is_following:
            return
        self._task = asyncio.create_task(self._follow_loop(status_fn))

    async def stop_follow(self, status_fn: Optional[StatusFn] = None) -> None:
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

    async def _follow_loop(self, status_fn: StatusFn) -> None:
        smoother = PoseTargetSmoother(alpha=0.7)
        min_interval = 1.0 / _FOLLOW_DISPATCH_HZ
        try:
            await status_fn({"type": "follow_status", "active": True})
            async with websockets.connect(VISION_WS_URL, max_queue=8) as ws:
                last_dispatch = 0.0
                while True:
                    raw = await ws.recv()
                    data = json.loads(raw)
                    if data.get("type") not in (None, "pose_update"):
                        continue

                    now = asyncio.get_event_loop().time()
                    if now - last_dispatch < min_interval:
                        continue

                    body = data.get("body_landmarks") or []
                    head = data.get("head_pose")
                    if not body:
                        continue

                    targets = compute_joint_targets(body, head)
                    if not targets:
                        continue
                    targets = smoother.smooth(targets)

                    commands = targets_to_servo_commands(targets, _FOLLOW_DURATION_MS)
                    await self._dispatch(commands)
                    last_dispatch = now
        except asyncio.CancelledError:
            logger.info("Follow loop cancelled")
            raise
        except Exception as exc:
            logger.warning("Follow loop error: %s", exc)
            await status_fn({"type": "follow_status", "active": False, "error": str(exc)})

    async def trigger_capture_and_mimic(self, status_fn: StatusFn) -> None:
        if self.is_capturing:
            return
        self._capture_task = asyncio.create_task(self._capture_flow(status_fn))

    async def _capture_flow(self, status_fn: StatusFn) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                resp = await http.post(f"{VISION_HTTP_BASE}/capture/stable_position/start")
                resp.raise_for_status()

            await status_fn({"type": "capture_status", "stage": "started"})

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
                            await status_fn({
                                "type": "capture_status",
                                "stage": "countdown",
                                "countdown_remaining": stability.get("countdown_remaining"),
                            })
                        elif state == "collecting":
                            await status_fn({
                                "type": "capture_status",
                                "stage": "collecting",
                                "progress": stability.get("collection_progress"),
                            })
                        elif state == "frozen":
                            frozen_landmarks = data.get("body_landmarks") or []
                            frozen_head = data.get("head_pose")
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

            targets = compute_joint_targets(frozen_landmarks, frozen_head)
            commands = targets_to_servo_commands(targets, _CAPTURE_DURATION_MS)
            await self._dispatch(commands)

            # Release vision-side freeze so subsequent captures work
            async with httpx.AsyncClient(timeout=5.0) as http:
                try:
                    await http.post(f"{VISION_HTTP_BASE}/capture/stable_position/continue")
                except Exception as e:
                    logger.debug("Vision continue post failed: %s", e)

            await status_fn({"type": "capture_status", "stage": "done"})

        except asyncio.TimeoutError:
            logger.warning("Capture flow timed out waiting for frozen frame")
            await status_fn({"type": "capture_status", "stage": "error", "error": "timeout"})
        except Exception as exc:
            logger.warning("Capture flow error: %s", exc)
            await status_fn({"type": "capture_status", "stage": "error", "error": str(exc)})
