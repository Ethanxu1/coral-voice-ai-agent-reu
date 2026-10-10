"""Immutable, safety-preflighted robot motion sequence playback."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from app.robot.angle_utils import rad_to_servo_units
from app.robot.interface import ServoCommand
from app.robot.servo_config import SERVO_ID_MAP
from app.services.motion import (
    RobotServerUnavailable,
    dispatch_servo_commands,
    validate_motion_path,
)
from app.studio.models import RobotPose, Sequence


class OutputMode(str, Enum):
    SIMULATOR = "simulator"
    LIVE_ROBOT = "live_robot"


@dataclass(frozen=True, slots=True)
class SequenceStepSnapshot:
    robot_pose_id: str
    joints: tuple[tuple[str, float], ...]
    hold_ms: int
    transition_ms: int

    def joint_targets(self) -> dict[str, float]:
        return dict(self.joints)


@dataclass(frozen=True, slots=True)
class SequenceSnapshot:
    id: str
    name: str
    steps: tuple[SequenceStepSnapshot, ...]


@dataclass(frozen=True, slots=True)
class SequenceSafetyReport:
    safe: bool
    failed_step: int | None
    reason: str | None
    reports: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class PlaybackResult:
    status: str
    completed_steps: int
    failed_step: int | None = None
    reason: str | None = None

    @classmethod
    def blocked(cls, failed_step: int | None, reason: str | None) -> PlaybackResult:
        return cls("blocked", 0, failed_step, reason)

    @classmethod
    def hardware_unavailable(cls, completed_steps: int) -> PlaybackResult:
        return cls("hardware_unavailable", completed_steps, completed_steps, "offline")


class SequenceRepository(Protocol):
    def get_sequence(self, sequence_id: str) -> Sequence: ...

    def get_robot_pose(self, pose_id: str) -> RobotPose: ...


SafetyValidator = Callable[[SequenceSnapshot], SequenceSafetyReport]
Dispatcher = Callable[[list[ServoCommand], bool | None], Awaitable[None]]
Sleeper = Callable[[float], Awaitable[None]]


class SequencePlayer:
    """Preflight a whole sequence, then dispatch it serially."""

    def __init__(
        self,
        repository: SequenceRepository,
        simulator: Any,
        *,
        safety_validator: SafetyValidator | None = None,
        dispatcher: Dispatcher = dispatch_servo_commands,
        sleeper: Sleeper = asyncio.sleep,
    ) -> None:
        self._repository = repository
        self._simulator = simulator
        self._safety_validator = safety_validator or self._validate_snapshot
        self._dispatcher = dispatcher
        self._sleeper = sleeper
        self.output_mode = OutputMode.SIMULATOR
        self.dispatch_count = 0

    def preflight(self, sequence_id: str) -> SequenceSafetyReport:
        return self._safety_validator(self._snapshot(sequence_id))

    async def play(
        self, sequence_id: str, output_mode: OutputMode
    ) -> PlaybackResult:
        snapshot = self._snapshot(sequence_id)
        safety = self._safety_validator(snapshot)
        if not safety.safe:
            return PlaybackResult.blocked(safety.failed_step, safety.reason)

        self.output_mode = output_mode
        for step_index, step in enumerate(snapshot.steps):
            commands = self._commands_for(step)
            try:
                await self._dispatcher(
                    commands, output_mode is OutputMode.SIMULATOR
                )
            except RobotServerUnavailable:
                self.output_mode = OutputMode.SIMULATOR
                return PlaybackResult.hardware_unavailable(step_index)
            self.dispatch_count += 1
            await self._sleeper(step.hold_ms / 1000)
        return PlaybackResult("completed", len(snapshot.steps))

    async def preview_pose(self, pose_id: str) -> PlaybackResult:
        """Safety-check and display one saved pose in the simulator only."""
        pose = self._repository.get_robot_pose(pose_id)
        step = SequenceStepSnapshot(
            robot_pose_id=pose.id,
            joints=tuple(sorted(pose.joints.items())),
            hold_ms=0,
            transition_ms=300,
        )
        snapshot = SequenceSnapshot(f"pose-preview:{pose.id}", pose.name, (step,))
        safety = self._safety_validator(snapshot)
        if not safety.safe:
            return PlaybackResult.blocked(safety.failed_step, safety.reason)

        await self._dispatcher(self._commands_for(step), True)
        self.output_mode = OutputMode.SIMULATOR
        self.dispatch_count += 1
        return PlaybackResult("completed", 1)

    def _snapshot(self, sequence_id: str) -> SequenceSnapshot:
        sequence = self._repository.get_sequence(sequence_id)
        steps = []
        for step in sequence.steps:
            pose = self._repository.get_robot_pose(step.robot_pose_id)
            steps.append(
                SequenceStepSnapshot(
                    robot_pose_id=pose.id,
                    joints=tuple(sorted(pose.joints.items())),
                    hold_ms=step.hold_ms,
                    transition_ms=step.transition_ms,
                )
            )
        return SequenceSnapshot(sequence.id, sequence.name, tuple(steps))

    def _validate_snapshot(self, snapshot: SequenceSnapshot) -> SequenceSafetyReport:
        result = validate_motion_path(
            self._simulator,
            [step.joint_targets() for step in snapshot.steps],
            f"studio sequence {snapshot.id}",
        )
        return SequenceSafetyReport(
            result.safe,
            result.failed_step,
            result.reason,
            result.reports,
        )

    @staticmethod
    def _commands_for(step: SequenceStepSnapshot) -> list[ServoCommand]:
        return [
            ServoCommand(
                servo_id=SERVO_ID_MAP[joint],
                position=rad_to_servo_units(value),
                duration_ms=step.transition_ms,
            )
            for joint, value in step.joints
            if joint in SERVO_ID_MAP
        ]
