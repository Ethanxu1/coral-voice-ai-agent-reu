"""Recognition-to-rule execution event flow tests."""

from __future__ import annotations

from pathlib import Path

import asyncio

from app.studio.models import Sequence as MotionSequence
from app.studio.recognizer import RecognitionResult
from app.studio.repository import StudioRepository
from app.studio.runtime import StudioRuntime
from app.studio.sequence_player import OutputMode, PlaybackResult


def _run_immediate(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("Test coroutine unexpectedly suspended")


class FakeRecognizer:
    def __init__(self, label: str) -> None:
        self.label = label

    def classify(self, subject_id, _features):
        return RecognitionResult(subject_id, self.label, 0.91, 0.2, "recognized")


class RejectingRecognizer:
    def classify(self, subject_id, _features):
        return RecognitionResult(subject_id, None, 0.71, 0.4, "out_of_distribution")


class FakePlayer:
    def __init__(self) -> None:
        self.output_mode = OutputMode.SIMULATOR
        self.played: list[str] = []

    async def play(self, sequence_id: str, output_mode: OutputMode) -> PlaybackResult:
        self.played.append(sequence_id)
        return PlaybackResult("completed", 1)


def _landmarks() -> list[dict[str, float]]:
    points = [
        {"x": 0.5, "y": 0.5, "z": 0.0, "visibility": 0.95}
        for _ in range(33)
    ]
    coordinates = {
        0: (0.5, 0.1), 11: (0.4, 0.3), 12: (0.6, 0.3),
        13: (0.3, 0.45), 14: (0.7, 0.45), 15: (0.2, 0.6),
        16: (0.8, 0.6), 23: (0.44, 0.55), 24: (0.56, 0.55),
        25: (0.42, 0.75), 26: (0.58, 0.75), 27: (0.4, 0.95),
        28: (0.6, 0.95),
    }
    for index, (x, y) in coordinates.items():
        points[index].update(x=x, y=y)
    return points


def test_runtime_recognizes_any_subject_and_executes_rule(tmp_path: Path) -> None:
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Classroom")
    pose = repo.create_human_pose(project.id, "Hands up", 0.78, 0.7)
    robot = repo.create_robot_pose(project.id, "Wave", {"r_sho_pitch": 0.4})
    sequence: MotionSequence = repo.create_sequence(
        project.id, "Wave", [{"robot_pose_id": robot.id}]
    )
    repo.create_behavior_rule(project.id, pose.id, sequence.id, 2.0)
    player = FakePlayer()
    runtime = StudioRuntime(repo, player, recognizer=FakeRecognizer(pose.id))
    events = runtime.subscribe()
    frame = {"subjects": [{"id": "person-2", "body_landmarks": _landmarks()}]}

    _run_immediate(runtime.handle_pose_payload(frame, now=0.0))
    _run_immediate(runtime.handle_pose_payload(frame, now=0.7))
    assert player.played == []

    runtime.set_trigger_enabled(True)
    _run_immediate(runtime.handle_pose_payload(frame, now=1.0))
    _run_immediate(runtime.handle_pose_payload(frame, now=1.7))
    emitted = []
    while not events.empty():
        emitted.append(events.get_nowait())

    assert player.played == [sequence.id]
    assert any(event.type == "recognition" and event.subject_id == "person-2" for event in emitted)
    assert any(event.type == "execution_completed" for event in emitted)


def test_deleted_interaction_stops_hold_progress_and_execution(tmp_path: Path) -> None:
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Classroom")
    pose = repo.create_human_pose(project.id, "Hands up", 0.78, 0.7)
    robot = repo.create_robot_pose(project.id, "Wave", {"r_sho_pitch": 0.4})
    sequence = repo.create_sequence(
        project.id,
        "__interaction_pose__:hands-up:wave",
        [{"robot_pose_id": robot.id}],
    )
    rule = repo.create_behavior_rule(project.id, pose.id, sequence.id, 2.0)
    player = FakePlayer()
    runtime = StudioRuntime(repo, player, recognizer=FakeRecognizer(pose.id))
    events = runtime.subscribe()
    frame = {"subjects": [{"id": "person-2", "body_landmarks": _landmarks()}]}

    runtime.set_trigger_enabled(True)
    _run_immediate(runtime.handle_pose_payload(frame, now=0.0))
    while not events.empty():
        events.get_nowait()

    assert repo.delete_interaction(rule.id) is True
    _run_immediate(runtime.handle_pose_payload(frame, now=0.7))
    emitted = []
    while not events.empty():
        emitted.append(events.get_nowait())

    assert player.played == []
    assert [
        event.progress for event in emitted if event.type == "hold_progress"
    ] == [0.0]


def test_runtime_publishes_the_recognition_rejection_reason(tmp_path: Path) -> None:
    repo = StudioRepository(tmp_path / "studio.db")
    runtime = StudioRuntime(repo, FakePlayer(), recognizer=RejectingRecognizer())
    events = runtime.subscribe()

    _run_immediate(runtime.handle_pose_payload(
        {"subjects": [{"id": "person-2", "body_landmarks": _landmarks()}]},
        now=0.0,
    ))

    event = events.get_nowait()
    assert event.type == "recognition"
    assert event.reason == "out_of_distribution"


def test_preview_is_rejected_while_live_mode_transition_is_pending() -> None:
    class TransitionPlayer(FakePlayer):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.preview_calls = 0

        async def prepare_live_output(self) -> None:
            self.started.set()
            await self.release.wait()

        async def preview_sequence(self, _sequence_id: str) -> PlaybackResult:
            self.preview_calls += 1
            return PlaybackResult("completed", 1)

    async def exercise() -> tuple[PlaybackResult, int]:
        player = TransitionPlayer()
        runtime = StudioRuntime(object(), player, recognizer=FakeRecognizer("pose"))
        transition = asyncio.create_task(runtime.set_output_mode(OutputMode.LIVE_ROBOT))
        await player.started.wait()
        back_to_simulator = asyncio.create_task(
            runtime.set_output_mode(OutputMode.SIMULATOR)
        )
        await asyncio.sleep(0)
        preview = await runtime.preview("sequence")
        player.release.set()
        await asyncio.gather(transition, back_to_simulator)
        return preview, player.preview_calls

    preview, preview_calls = asyncio.run(exercise())

    assert preview.status == "blocked"
    assert preview.reason == "switch_to_simulator"
    assert preview_calls == 0
