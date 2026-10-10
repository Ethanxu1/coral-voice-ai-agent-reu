"""Safety-first sequence playback tests."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.motion import RobotServerUnavailable
from app.studio.models import RobotPose, Sequence, SequenceStep
from app.studio.sequence_player import (
    OutputMode,
    SequencePlayer,
    SequenceSafetyReport,
)


def _run_immediate(coroutine):
    """Run a coroutine whose injected async dependencies never suspend."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("Test coroutine unexpectedly suspended")


class FakeRepository:
    def __init__(self) -> None:
        self.poses = {
            f"pose-{index}": RobotPose(
                f"pose-{index}",
                "project-1",
                f"Pose {index}",
                {"l_sho_pitch": index * 0.2},
                "",
                "simulator",
                {"safe": True},
                "now",
                "now",
            )
            for index in range(3)
        }
        steps = tuple(
            SequenceStep(
                f"step-{index}",
                "sequence-1",
                f"pose-{index}",
                index,
                0,
                250,
            )
            for index in range(3)
        )
        self.sequence = Sequence(
            "sequence-1", "project-1", "Wave", steps, "now", "now"
        )

    def get_sequence(self, sequence_id: str) -> Sequence:
        assert sequence_id == self.sequence.id
        return self.sequence

    def get_robot_pose(self, pose_id: str) -> RobotPose:
        return self.poses[pose_id]


@dataclass
class FakeSafetyValidator:
    fail_on_step: int | None = None
    checked_steps: int = 0

    def __call__(self, snapshot) -> SequenceSafetyReport:
        self.checked_steps = len(snapshot.steps)
        if self.fail_on_step is not None:
            return SequenceSafetyReport(
                False, self.fail_on_step, "fall_risk", tuple()
            )
        return SequenceSafetyReport(True, None, None, tuple())


class FakeDispatch:
    def __init__(self) -> None:
        self.command_batches = 0
        self.disconnect_after_first_command = False

    async def __call__(self, commands, sim_only=None) -> None:
        if (
            self.disconnect_after_first_command
            and not sim_only
            and self.command_batches >= 1
        ):
            raise RobotServerUnavailable("offline")
        self.command_batches += 1


async def _no_sleep(_seconds: float) -> None:
    return None


def _player(checker: FakeSafetyValidator, hardware: FakeDispatch) -> SequencePlayer:
    return SequencePlayer(
        FakeRepository(),
        simulator=None,
        safety_validator=checker,
        dispatcher=hardware,
        sleeper=_no_sleep,
    )


def test_unsafe_middle_transition_blocks_entire_sequence() -> None:
    checker = FakeSafetyValidator(fail_on_step=1)
    hardware = FakeDispatch()
    player = _player(checker, hardware)

    result = _run_immediate(player.play("sequence-1", OutputMode.SIMULATOR))

    assert result.status == "blocked"
    assert result.failed_step == 1
    assert player.dispatch_count == 0
    assert hardware.command_batches == 0


def test_preflight_checks_every_transition_before_dispatch() -> None:
    checker = FakeSafetyValidator()
    hardware = FakeDispatch()
    player = _player(checker, hardware)

    result = _run_immediate(player.play("sequence-1", OutputMode.SIMULATOR))

    assert result.status == "completed"
    assert checker.checked_steps == 3
    assert hardware.command_batches == 3


def test_hardware_disconnect_forces_simulator() -> None:
    checker = FakeSafetyValidator()
    hardware = FakeDispatch()
    hardware.disconnect_after_first_command = True
    player = _player(checker, hardware)

    result = _run_immediate(player.play("sequence-1", OutputMode.LIVE_ROBOT))

    assert result.status == "hardware_unavailable"
    assert player.output_mode is OutputMode.SIMULATOR
    assert hardware.command_batches == 1


def test_simulator_is_the_default_output_mode() -> None:
    player = _player(FakeSafetyValidator(), FakeDispatch())

    assert player.output_mode is OutputMode.SIMULATOR
