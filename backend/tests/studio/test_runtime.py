"""Recognition-to-rule execution event flow tests."""

from __future__ import annotations

from pathlib import Path

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
    emitted = []
    while not events.empty():
        emitted.append(events.get_nowait())

    assert player.played == [sequence.id]
    assert any(event.type == "recognition" and event.subject_id == "person-2" for event in emitted)
    assert any(event.type == "execution_completed" for event in emitted)
