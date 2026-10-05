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
from typing import Awaitable, Callable, Optional

import httpx
import websockets

from loguru import logger

from app import config
from app.robot.interface import ServoCommand
from app.follow_walking import FollowWalking, WalkFn
from app.services.clean_logger import CleanLogger
from app.vision.leg_lift_controller import ANKLES, LEG_JOINTS, LegLiftController, _stand
from app.vision.pose_to_robot import (
    _STAND_LEG_TARGETS,
    JointAngleSmoother,
    compute_joint_targets,
    targets_to_servo_commands,
)

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


def legs_follow_person(sim_only: bool | None) -> bool:
    """Whether follow mode may move the legs this session.

    Not on the real robot unless config.HARDWARE_LEG_MIMICRY: one-foot
    stance sags ~10 deg there and isn't solved, and on 2026-10-02 the camera
    misread lost legs as raised during arms-only follow -- the robot slid its
    hips and tipped over. The sim (or the sim-only toggle) keeps leg mimicry.
    """
    from app.services.motion import sends_to_hardware

    return config.HARDWARE_LEG_MIMICRY or not sends_to_hardware(sim_only)


def robot_marches_with_person(sim_only: bool | None) -> bool:
    """Whether a marching person starts the real robot's walking engine
    (config.FOLLOW_WALKING; the sim has no walking engine)."""
    from app.services.motion import sends_to_hardware

    return config.FOLLOW_WALKING and sends_to_hardware(sim_only)


def pin_legs_to_stand(targets: dict[str, float]) -> dict[str, float]:
    """`targets` with every leg and ankle joint held at the stand pose."""
    return {**targets, **{j: _stand(j) for j in LEG_JOINTS + ANKLES}}


class FollowController:
    def __init__(self, dispatch_fn: DispatchFn, stream_fn: Optional[DispatchFn] = None,
                 walk_fn: Optional[WalkFn] = None):
        self._dispatch = dispatch_fn
        # Starts (True) / stops (False) the real robot's walking engine; see
        # app/follow_walking.py. None: marching is never handed over.
        self._walk_fn = walk_fn
        # Live ticks go through stream_fn when given: on the real robot the
        # blocking dispatch waits ~0.3 s per 45 ms move (2026-10-02), so a
        # 20 Hz stream must not wait. The seed move keeps the blocking path.
        self._live_dispatch = stream_fn or dispatch_fn
        self._task: Optional[asyncio.Task] = None
        self._capture_task: Optional[asyncio.Task] = None
        self._safety_gate = None

    async def _ensure_safety_gate(self):
        """Build the CBF safety gate once, off the event loop.

        Constructing it loads its own MuJoCo model and runs a real
        physics settle (~0.1s) — small, but it's blocking CPU work, so
        it goes in a thread and is cached rather than rebuilt per
        session. Returns None when the filter is disabled or fails to
        build: follow mode must still run, just unfiltered, exactly as
        it did before this layer existed.
        """
        if not config.ENABLE_FOLLOW_SAFETY:
            return None
        if self._safety_gate is None:
            from app.balance.safety_filter import FollowSafetyGate

            try:
                self._safety_gate = await asyncio.to_thread(FollowSafetyGate)
            except Exception as e:
                logger.warning("Safety gate unavailable, follow will run unfiltered: {}", e)
                return None
        self._safety_gate.reset()
        return self._safety_gate

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
            logger.debug("Vision continue on follow-start failed: {}", e)
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
        safety_gate = await self._ensure_safety_gate()
        # Sequences leg lifts (weight shift -> settle -> lift) so the robot
        # can raise a foot visibly without toppling. Only meaningful when
        # legs are tracked; fresh per session so no state leaks across.
        legs_pinned = not legs_follow_person(sim_only)
        if legs_pinned:
            logger.info("Follow: real robot -- legs held at stand, arms follow "
                        "(CORAL_HARDWARE_LEG_MIMICRY=false)")
        lift_ctl = (LegLiftController()
                    if config.ENABLE_LEG_TRACKING and not legs_pinned else None)
        last_ctl_t = 0.0
        walking = (FollowWalking(self._walk_fn)
                   if self._walk_fn is not None and robot_marches_with_person(sim_only)
                   else None)
        # The controller applies its own phase-dependent leg limit, so it
        # needs the unlimited retargeting; so does the march detector, which
        # only reads the legs (they are pinned) -- under the static cap
        # every knee raise reads the same 0.15. Otherwise keep the cap.
        uncapped = lift_ctl is not None or (walking is not None and legs_pinned)
        leg_limit = 1.0 if uncapped else None

        try:
            await status_fn({"type": "follow_status", "active": True})
            from app.services.pose_recording import recorder_if_enabled

            recorder = recorder_if_enabled()
            if recorder is not None:
                logger.info("Follow: recording camera keypoints to {}", recorder.path)
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
                            if recorder is not None:
                                recorder.write(data)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.warning("Follow reader exited: {}", e)
                        if clean_logger is not None:
                            clean_logger.follow_error("vision reader exited", e)

                def _log_dispatch_error(t: asyncio.Task) -> None:
                    if t.cancelled():
                        return
                    exc = t.exception()
                    if exc is not None:
                        logger.warning("Follow dispatch error: {}", exc)

                reader_task = asyncio.create_task(reader())
                in_flight: Optional[asyncio.Task] = None
                dispatch_count = 0
                skip_count = 0
                empty_target_count = 0
                safety_hold_count = 0
                # Most recent leg command, logged each heartbeat. Leg
                # poses are what topple this robot, and reproducing what
                # live retargeting emits from synthetic landmarks has
                # proved unreliable -- so record the real thing.
                last_leg_targets: dict[str, float] | None = None
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
                        targets = compute_joint_targets(
                            body, head, leg_travel_limit=leg_limit,
                            omit_untrusted_legs=lift_ctl is not None,
                        ) if body else {}
                        if not targets:
                            # Person partly out of frame — try again on the next push.
                            latest_event.clear()
                            continue
                        targets = smoother.smooth(targets)
                        if legs_pinned:
                            targets = pin_legs_to_stand(targets)
                        if lift_ctl is not None:
                            # dt=0: legs and ankles are commanded at stand for
                            # the seed. A lift, if the person is already doing
                            # one, is then sequenced properly from the loop.
                            targets = lift_ctl.update(targets, 0.0)
                            last_ctl_t = asyncio.get_event_loop().time()
                        # The seed is the single largest move of a follow
                        # session (STAND straight to the human's first pose),
                        # so it gets filtered like any other frame.
                        if safety_gate is not None:
                            targets, seed_held = safety_gate.filter_targets(targets)
                            if seed_held:
                                logger.info(
                                    "Follow: safety filter scaled back the seed pose "
                                    "(margin {:.4f})", safety_gate.last_margin or 0.0,
                                )
                        seed_cmds = targets_to_servo_commands(targets, _FOLLOW_SEED_DURATION_MS)
                        logger.info("Follow: seeding initial pose ({} joints)", len(seed_cmds))
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
                        targets = compute_joint_targets(
                            body, head, leg_travel_limit=leg_limit,
                            omit_untrusted_legs=lift_ctl is not None,
                        ) if body else {}
                        if walking is not None:
                            was_marching = walking.marching
                            if walking.update(targets, asyncio.get_event_loop().time(), body):
                                # The walking engine has the legs; arms still follow.
                                if targets:
                                    targets = pin_legs_to_stand(targets)
                                if lift_ctl is not None:
                                    lift_ctl.reset()
                            if walking.marching != was_marching:
                                await status_fn({"type": "follow_status", "active": True,
                                                 "marching": walking.marching})
                        if not targets:
                            empty_target_count += 1
                        else:
                            targets = smoother.smooth(targets)
                            if legs_pinned:
                                targets = pin_legs_to_stand(targets)
                            if in_flight is not None and not in_flight.done():
                                skip_count += 1
                            else:
                                # Filter inside the dispatch branch, not before
                                # it: the gate tracks the pose the robot was
                                # actually COMMANDED, so letting a skipped tick
                                # advance it would leave the gate measuring the
                                # next frame from a pose that was never sent.
                                if lift_ctl is not None:
                                    # Advanced only on frames that are actually
                                    # dispatched, with real elapsed time, for the
                                    # same reason as the gate below.
                                    now_t = asyncio.get_event_loop().time()
                                    targets = lift_ctl.update(targets, now_t - last_ctl_t)
                                    last_ctl_t = now_t
                                if safety_gate is not None:
                                    targets, held_back = safety_gate.filter_targets(targets)
                                    if held_back:
                                        safety_hold_count += 1
                                last_leg_targets = {
                                    j: round(v, 4) for j, v in targets.items()
                                    if j in _STAND_LEG_TARGETS or j in ANKLES
                                } or None
                                commands = targets_to_servo_commands(targets, _FOLLOW_DURATION_MS)
                                in_flight = asyncio.create_task(self._live_dispatch(commands, sim_only))
                                in_flight.add_done_callback(_log_dispatch_error)
                                dispatch_count += 1

                        # 2-second heartbeat: shows whether we're flowing.
                        now = asyncio.get_event_loop().time()
                        if now - last_heartbeat >= 2.0:
                            margin = None if safety_gate is None else safety_gate.last_margin
                            margin_str = "n/a" if margin is None else f"{margin:.4f}"
                            logger.info(
                                "Follow: {} dispatches, {} skips, {} empty-targets, "
                                "{} safety-holds in last 2s (stability margin {})",
                                dispatch_count, skip_count, empty_target_count,
                                safety_hold_count, margin_str,
                            )
                            if clean_logger is not None:
                                clean_logger.follow_tick(
                                    dispatch_count, skip_count, empty_target_count,
                                    safety_holds=None if safety_gate is None else safety_hold_count,
                                    stability_margin=margin,
                                    leg_targets=last_leg_targets,
                                    lift_phase=None if lift_ctl is None else lift_ctl.phase.value,
                                    leg_reading=None if lift_ctl is None else lift_ctl.take_reading(),
                                )
                            dispatch_count = skip_count = empty_target_count = 0
                            safety_hold_count = 0
                            last_heartbeat = now
                finally:
                    if walking is not None:
                        await walking.close()
                    reader_task.cancel()
                    if in_flight is not None and not in_flight.done():
                        in_flight.cancel()
                    if recorder is not None:
                        recorder.close()
        except asyncio.CancelledError:
            logger.info("Follow loop cancelled")
            if clean_logger is not None:
                clean_logger.follow_stopped(reason="cancelled")
            raise
        except Exception as exc:
            logger.warning("Follow loop error: {}", exc)
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
                    logger.debug("Vision continue post failed: {}", e)

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
            logger.warning("Capture flow error: {}", exc)
            if clean_logger is not None:
                clean_logger.capture_error("flow failed", exc)
            await status_fn({"type": "capture_status", "stage": "error", "error": str(exc)})
