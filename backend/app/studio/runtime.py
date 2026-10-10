"""Live recognition, trigger arbitration, playback, and event broadcasting."""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from loguru import logger

from app.studio.features import InvalidPose, PoseFeatures, extract_pose_features
from app.studio.recognizer import (
    PoseRecognizer,
    RecognizerSample,
    WeightedKnnRecognizer,
)
from app.studio.repository import StudioRepository
from app.studio.sequence_player import OutputMode, PlaybackResult, SequencePlayer
from app.studio.trigger_engine import TriggerEngine


@dataclass(frozen=True, slots=True)
class StudioEvent:
    type: str
    subject_id: str | None = None
    label: str | None = None
    confidence: float | None = None
    progress: float | None = None
    sequence_id: str | None = None
    failed_step: int | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


class _DisabledPlayer:
    output_mode = OutputMode.SIMULATOR

    async def play(self, _sequence_id: str, _mode: OutputMode) -> PlaybackResult:
        return PlaybackResult("blocked", 0, reason="Runtime disabled")

    async def preview_pose(self, _pose_id: str) -> PlaybackResult:
        return PlaybackResult("blocked", 0, reason="Runtime disabled")


class StudioRuntime:
    """Connect vision subjects to few-shot recognition and safe sequences."""

    def __init__(
        self,
        repository: StudioRepository,
        player: SequencePlayer | Any,
        *,
        recognizer: PoseRecognizer | None = None,
        trigger_engine: TriggerEngine | None = None,
        vision_url: str = "ws://127.0.0.1:8001/ws/pose",
        vision_enable_url: str = "http://127.0.0.1:8001/subject-selection/start",
    ) -> None:
        self._repository = repository
        self._player = player
        self._recognizer = recognizer or self._build_recognizer()
        self._trigger_engine = trigger_engine or TriggerEngine()
        self._vision_url = vision_url
        self._vision_enable_url = vision_enable_url
        self._subscribers: set[asyncio.Queue[StudioEvent]] = set()
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self.output_mode = OutputMode.SIMULATOR

    @classmethod
    def disabled(cls, repository: StudioRepository) -> StudioRuntime:
        return cls(repository, _DisabledPlayer(), recognizer=WeightedKnnRecognizer([]))

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._consume_vision())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def set_output_mode(self, mode: OutputMode | str) -> OutputMode:
        self.output_mode = OutputMode(mode)
        return self.output_mode

    def subscribe(self) -> asyncio.Queue[StudioEvent]:
        queue: asyncio.Queue[StudioEvent] = asyncio.Queue(maxsize=200)
        self._subscribers.add(queue)
        return queue

    async def preview(self, sequence_id: str) -> PlaybackResult:
        return await self._player.play(sequence_id, OutputMode.SIMULATOR)

    async def preview_pose(self, pose_id: str) -> PlaybackResult:
        return await self._player.preview_pose(pose_id)

    def unsubscribe(self, queue: asyncio.Queue[StudioEvent]) -> None:
        self._subscribers.discard(queue)

    def refresh_recognizer(self) -> None:
        self._recognizer = self._build_recognizer()

    async def handle_pose_payload(
        self, payload: dict[str, Any], *, now: float | None = None
    ) -> None:
        timestamp = time.monotonic() if now is None else now
        results = []
        for subject in payload.get("subjects") or []:
            subject_id = str(subject.get("id", "unknown"))
            try:
                features = extract_pose_features(subject.get("body_landmarks") or [])
            except InvalidPose:
                continue
            normalized = PoseFeatures(
                tuple(f"feature_{index}" for index in range(len(features.values))),
                features.values,
                features.weights,
            )
            result = self._recognizer.classify(subject_id, normalized)
            results.append(result)
            self._publish(
                StudioEvent(
                    "recognition",
                    subject_id=subject_id,
                    label=result.label,
                    confidence=result.confidence,
                )
            )

        decision = self._trigger_engine.update(results, timestamp)
        snapshot = self._trigger_engine.snapshot(timestamp)
        for hold in snapshot.holds:
            self._publish(
                StudioEvent(
                    "hold_progress",
                    subject_id=hold.subject_id,
                    label=hold.label,
                    confidence=hold.confidence,
                    progress=hold.progress,
                )
            )
        if decision is None:
            return

        matching_rules = [
            rule
            for project in self._repository.list_projects()
            for rule in self._repository.list_behavior_rules(project.id)
            if rule.enabled and rule.human_pose_id == decision.label
        ]
        if not matching_rules:
            return
        rule = min(matching_rules, key=lambda item: (-item.priority, item.id))
        self._trigger_engine.mark_execution_started()
        self._publish(
            StudioEvent(
                "execution_started",
                subject_id=decision.subject_id,
                label=decision.label,
                sequence_id=rule.sequence_id,
            )
        )
        result = await self._player.play(rule.sequence_id, self.output_mode)
        self._trigger_engine.mark_execution_finished(timestamp, rule.cooldown_seconds)
        if result.status == "completed":
            event_type = "execution_completed"
            message = "Sequence completed"
        elif result.status == "hardware_unavailable":
            self.output_mode = OutputMode.SIMULATOR
            event_type = "hardware_unavailable"
            message = "Hardware unavailable; switched to Simulator"
        else:
            event_type = "execution_blocked"
            message = "Fall or collision risk detected"
        self._publish(
            StudioEvent(
                event_type,
                subject_id=decision.subject_id,
                sequence_id=rule.sequence_id,
                failed_step=result.failed_step,
                message=message,
            )
        )

    def _build_recognizer(self) -> WeightedKnnRecognizer:
        samples: list[RecognizerSample] = []
        for project in self._repository.list_projects():
            for pose in self._repository.list_human_poses(project.id):
                if not pose.enabled:
                    continue
                for sample in self._repository.list_pose_samples(pose.id):
                    names = tuple(
                        f"feature_{index}" for index in range(len(sample.features))
                    )
                    samples.append(
                        RecognizerSample(
                            pose.id,
                            PoseFeatures(names, tuple(sample.features), tuple(sample.weights)),
                        )
                    )
        return WeightedKnnRecognizer(samples)

    def _publish(self, event: StudioEvent) -> None:
        for queue in tuple(self._subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    async def _consume_vision(self) -> None:
        import websockets

        while self._running:
            try:
                await asyncio.to_thread(self._enable_multi_person_vision)
                async with websockets.connect(self._vision_url) as socket:
                    async for raw_message in socket:
                        await self.handle_pose_payload(json.loads(raw_message))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug(f"Studio vision stream unavailable: {exc}")
                await asyncio.sleep(1.0)

    def _enable_multi_person_vision(self) -> None:
        request = urllib.request.Request(self._vision_enable_url, method="POST")
        with urllib.request.urlopen(request, timeout=2):
            pass
