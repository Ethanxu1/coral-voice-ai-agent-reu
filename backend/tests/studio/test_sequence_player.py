"""Safety-first sequence playback tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.services.motion import MotionPathValidation, RobotServerUnavailable
from app.robot.interface import ServoCommand
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
    fall_is_warning: bool = False
    checked_steps: int = 0

    def __call__(self, snapshot) -> SequenceSafetyReport:
        self.checked_steps = len(snapshot.steps)
        if self.fail_on_step is not None:
            return SequenceSafetyReport(
                self.fall_is_warning,
                None if self.fall_is_warning else self.fail_on_step,
                "fall_risk",
                tuple(),
            )
        return SequenceSafetyReport(True, None, None, tuple())


class FakeDispatch:
    def __init__(self) -> None:
        self.command_batches = 0
        self.batches: list[list[ServoCommand]] = []
        self.disconnect_after_first_command = False
        self.sim_only_values: list[bool | None] = []

    async def __call__(self, commands, sim_only=None) -> None:
        if (
            self.disconnect_after_first_command
            and not sim_only
            and self.command_batches >= 1
        ):
            raise RobotServerUnavailable("offline")
        self.command_batches += 1
        self.batches.append(commands)
        self.sim_only_values.append(sim_only)


class FakeSimulator:
    def __init__(self) -> None:
        self.stabilized_for: list[float] = []
        self.reset_count = 0

    def enable_stabilized_preview(self, ttl_seconds: float) -> None:
        self.stabilized_for.append(ttl_seconds)

    def reset_pose(self) -> None:
        self.reset_count += 1


async def _no_sleep(_seconds: float) -> None:
    return None


def _player(
    checker: FakeSafetyValidator,
    hardware: FakeDispatch,
    simulator=None,
) -> SequencePlayer:
    return SequencePlayer(
        FakeRepository(),
        simulator=simulator,
        safety_validator=checker,
        preview_validator=checker,
        dispatcher=hardware,
        sleeper=_no_sleep,
    )


def test_unsafe_middle_transition_blocks_entire_live_robot_sequence() -> None:
    checker = FakeSafetyValidator(fail_on_step=1)
    hardware = FakeDispatch()
    player = _player(checker, hardware)

    result = _run_immediate(player.play("sequence-1", OutputMode.LIVE_ROBOT))

    assert result.status == "blocked"
    assert result.failed_step == 1
    assert player.dispatch_count == 0
    assert hardware.command_batches == 0


def test_triggered_simulator_playback_uses_stabilized_preview_path() -> None:
    checker = FakeSafetyValidator(fail_on_step=0)
    dispatcher = FakeDispatch()
    simulator = FakeSimulator()
    player = _player(checker, dispatcher, simulator)

    result = _run_immediate(player.play("sequence-1", OutputMode.SIMULATOR))

    assert result.status == "completed"
    assert checker.checked_steps == 0
    assert dispatcher.command_batches == 3
    assert dispatcher.sim_only_values == [True, True, True]
    assert simulator.stabilized_for and simulator.stabilized_for[0] >= 1.0


def test_live_robot_preflight_checks_every_transition_before_dispatch() -> None:
    checker = FakeSafetyValidator()
    hardware = FakeDispatch()
    player = _player(checker, hardware)

    result = _run_immediate(player.play("sequence-1", OutputMode.LIVE_ROBOT))

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


def test_pose_preview_always_displays_selected_pose_in_stabilized_simulator() -> None:
    checker = FakeSafetyValidator(fail_on_step=0)
    dispatcher = FakeDispatch()
    simulator = FakeSimulator()
    player = _player(checker, dispatcher, simulator)

    result = _run_immediate(player.preview_pose("pose-1"))

    assert result.status == "completed"
    assert checker.checked_steps == 0
    assert dispatcher.command_batches == 1
    assert dispatcher.batches == [[ServoCommand(servo_id=13, position=548, duration_ms=300)]]
    assert dispatcher.sim_only_values == [True]
    assert simulator.stabilized_for and simulator.stabilized_for[0] >= 1.0


def test_sequence_preview_plays_immediately_without_strict_preflight() -> None:
    checker = FakeSafetyValidator(fail_on_step=0, fall_is_warning=True)
    dispatcher = FakeDispatch()
    simulator = FakeSimulator()
    player = _player(checker, dispatcher, simulator)

    result = _run_immediate(player.preview_sequence("sequence-1"))

    assert result.status == "completed"
    assert result.reason is None
    assert checker.checked_steps == 0
    assert dispatcher.command_batches == 3
    assert dispatcher.sim_only_values == [True, True, True]
    assert simulator.stabilized_for and simulator.stabilized_for[0] >= 1.0


def test_direct_preview_never_interleaves_with_live_playback() -> None:
    class YieldingDispatch(FakeDispatch):
        async def __call__(self, commands, sim_only=None) -> None:
            await super().__call__(commands, sim_only)
            await asyncio.sleep(0)

    async def exercise() -> list[bool | None]:
        dispatcher = YieldingDispatch()
        player = _player(FakeSafetyValidator(), dispatcher, FakeSimulator())
        await asyncio.gather(
            player.play("sequence-1", OutputMode.LIVE_ROBOT),
            player.preview_sequence("sequence-1"),
        )
        return dispatcher.sim_only_values

    assert asyncio.run(exercise()) == [False, False, False, True, True, True]


def test_switching_to_live_resets_preview_state_before_strict_playback() -> None:
    async def exercise() -> tuple[int, list[bool | None]]:
        simulator = FakeSimulator()
        dispatcher = FakeDispatch()
        player = _player(FakeSafetyValidator(), dispatcher, simulator)
        await player.preview_sequence("sequence-1")
        await player.prepare_live_output()
        await player.play("sequence-1", OutputMode.LIVE_ROBOT)
        return simulator.reset_count, dispatcher.sim_only_values

    reset_count, modes = asyncio.run(exercise())

    assert reset_count == 1
    assert modes == [True, True, True, False, False, False]


def test_live_preflight_starts_from_physical_hardware_state(monkeypatch) -> None:
    captured_initial: list[dict[str, float] | None] = []

    def validate(_simulator, _frames, _context, *, initial=None):
        captured_initial.append(initial)
        return MotionPathValidation(True, None, None, tuple())

    async def hardware_state(_required: set[str]) -> dict[str, float]:
        return {"l_sho_pitch": 0.73}

    monkeypatch.setattr("app.studio.sequence_player.validate_motion_path", validate)
    player = SequencePlayer(
        FakeRepository(),
        FakeSimulator(),
        dispatcher=FakeDispatch(),
        sleeper=_no_sleep,
        hardware_state_provider=hardware_state,
    )

    result = asyncio.run(player.play("sequence-1", OutputMode.LIVE_ROBOT))

    assert result.status == "completed"
    assert captured_initial == [{"l_sho_pitch": 0.73}]


def test_live_preflight_fails_closed_on_incomplete_hardware_state() -> None:
    async def incomplete_state(_required: set[str]) -> dict[str, float]:
        return {}

    dispatcher = FakeDispatch()
    player = SequencePlayer(
        FakeRepository(),
        FakeSimulator(),
        dispatcher=dispatcher,
        sleeper=_no_sleep,
        hardware_state_provider=incomplete_state,
    )

    result = asyncio.run(player.play("sequence-1", OutputMode.LIVE_ROBOT))

    assert result.status == "hardware_unavailable"
    assert dispatcher.command_batches == 0
    assert player.output_mode is OutputMode.SIMULATOR
