"""End-to-end studio flow from five-shot training to simulator-only playback."""

from __future__ import annotations

from pathlib import Path

from app.studio.features import extract_pose_features
from app.studio.repository import StudioRepository
from app.studio.runtime import StudioRuntime
from app.studio.sequence_player import (
    OutputMode,
    SequencePlayer,
    SequenceSafetyReport,
)
from app.studio.trigger_engine import TriggerEngine


def _run_immediate(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("Coroutine unexpectedly suspended")


def _pose(*, hands_up: bool, offset: float = 0.0) -> list[dict[str, float]]:
    landmarks = [
        {"x": 0.5, "y": 0.5, "z": 0.0, "visibility": 0.98}
        for _ in range(33)
    ]
    points = {
        0: (0.50, 0.12), 11: (0.40, 0.32), 12: (0.60, 0.32),
        13: (0.34, 0.20 if hands_up else 0.48),
        14: (0.66, 0.20 if hands_up else 0.48),
        15: (0.30, 0.05 if hands_up else 0.64),
        16: (0.70, 0.05 if hands_up else 0.64),
        23: (0.44, 0.56), 24: (0.56, 0.56),
        25: (0.43, 0.76), 26: (0.57, 0.76),
        27: (0.42, 0.96), 28: (0.58, 0.96),
    }
    for index, (x, y) in points.items():
        landmarks[index].update(x=x + offset, y=y)
    return landmarks


class RecordingDispatch:
    def __init__(self) -> None:
        self.simulator_batches: list[list] = []
        self.hardware_batches: list[list] = []

    async def __call__(self, commands, sim_only=None) -> None:
        if sim_only:
            self.simulator_batches.append(commands)
        else:
            self.hardware_batches.append(commands)


async def _no_sleep(_seconds: float) -> None:
    return None


def test_any_person_can_trigger_one_safe_simulator_sequence(tmp_path: Path) -> None:
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Classroom")
    human_pose = repo.create_human_pose(project.id, "Hands up", 0.78, 0.7)
    for index in range(5):
        features = extract_pose_features(_pose(hands_up=True, offset=index * 0.001))
        repo.create_pose_sample(human_pose.id, features.values, features.weights)

    robot_poses = [
        repo.create_robot_pose(project.id, "Wave", {"r_sho_pitch": 0.4}),
        repo.create_robot_pose(project.id, "Crouch", {"l_knee": 0.35, "r_knee": -0.35}),
        repo.create_robot_pose(project.id, "Stand", {"l_knee": 0.0, "r_knee": 0.0}),
    ]
    sequence = repo.create_sequence(
        project.id,
        "Celebrate",
        [
            {"robot_pose_id": pose.id, "hold_ms": 0, "transition_ms": 200}
            for pose in robot_poses
        ],
    )
    repo.create_behavior_rule(project.id, human_pose.id, sequence.id, 2.0)
    dispatch = RecordingDispatch()
    player = SequencePlayer(
        repo,
        simulator=None,
        safety_validator=lambda snapshot: SequenceSafetyReport(
            True, None, None, tuple({"safe": True} for _ in snapshot.steps)
        ),
        dispatcher=dispatch,
        sleeper=_no_sleep,
    )
    runtime = StudioRuntime(
        repo,
        player,
        trigger_engine=TriggerEngine(hold_seconds=0.7, cooldown_seconds=2.0),
    )
    runtime.set_output_mode(OutputMode.SIMULATOR)
    events = runtime.subscribe()
    frame = {
        "subjects": [
            {"id": "p1", "body_landmarks": _pose(hands_up=False)},
            {"id": "p2", "body_landmarks": _pose(hands_up=True)},
        ]
    }

    _run_immediate(runtime.handle_pose_payload(frame, now=0.0))
    _run_immediate(runtime.handle_pose_payload(frame, now=0.7))
    emitted = []
    while not events.empty():
        emitted.append(events.get_nowait())

    assert len(dispatch.simulator_batches) == 3
    assert dispatch.hardware_batches == []
    assert player.output_mode is OutputMode.SIMULATOR
    started = [event for event in emitted if event.type == "execution_started"]
    assert [event.subject_id for event in started] == ["p2"]
