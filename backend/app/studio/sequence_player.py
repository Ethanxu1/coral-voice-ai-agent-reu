"""Immutable, safety-preflighted robot motion sequence playback."""

from __future__ import annotations

import asyncio
import math
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
    read_hardware_joint_states,
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
HardwareStateProvider = Callable[[set[str]], Awaitable[dict[str, float]]]


class SequencePlayer:
    """Preflight a whole sequence, then dispatch it serially."""

    def __init__(
        self,
        repository: SequenceRepository,
        simulator: Any,
        *,
        safety_validator: SafetyValidator | None = None,
        preview_validator: SafetyValidator | None = None,
        dispatcher: Dispatcher = dispatch_servo_commands,
        sleeper: Sleeper = asyncio.sleep,
        hardware_state_provider: HardwareStateProvider = read_hardware_joint_states,
    ) -> None:
        self._repository = repository
        self._simulator = simulator
        self._safety_validator = safety_validator or self._validate_snapshot
        self._uses_default_safety_validator = safety_validator is None
        # Retained as an injected compatibility seam for callers that build
        # players with both validators. Direct simulator playback does not use it.
        self._preview_validator = preview_validator
        self._dispatcher = dispatcher
        self._sleeper = sleeper
        self._hardware_state_provider = hardware_state_provider
        self._playback_lock = asyncio.Lock()
        self.output_mode = OutputMode.SIMULATOR
        self.dispatch_count = 0

    def preflight(self, sequence_id: str) -> SequenceSafetyReport:
        return self._safety_validator(self._snapshot(sequence_id))

    async def prepare_live_output(self) -> None:
        """Clear preview stabilization before accepting Live Robot mode."""
        async with self._playback_lock:
            reset_pose = getattr(self._simulator, "reset_pose", None)
            if callable(reset_pose):
                reset_pose()

    async def play(
        self, sequence_id: str, output_mode: OutputMode
    ) -> PlaybackResult:
        async with self._playback_lock:
            return await self._play_locked(sequence_id, output_mode)

    async def _play_locked(
        self, sequence_id: str, output_mode: OutputMode
    ) -> PlaybackResult:
        if output_mode is OutputMode.SIMULATOR:
            return await self._preview_sequence_locked(sequence_id)

        snapshot = self._snapshot(sequence_id)
        if output_mode is OutputMode.LIVE_ROBOT and self._uses_default_safety_validator:
            required_joints = {
                joint for step in snapshot.steps for joint, _value in step.joints
            }
            try:
                initial = await self._hardware_state_provider(required_joints)
                if (
                    not initial
                    or required_joints - initial.keys()
                    or not all(math.isfinite(value) for value in initial.values())
                ):
                    raise RobotServerUnavailable("robot joint state is incomplete")
            except RobotServerUnavailable:
                self.output_mode = OutputMode.SIMULATOR
                return PlaybackResult.hardware_unavailable(0)
            safety = self._validate_snapshot(snapshot, initial=initial)
        else:
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
        """Display one saved pose in the stabilized simulator only."""
        async with self._playback_lock:
            return await self._preview_pose_locked(pose_id)

    async def _preview_pose_locked(self, pose_id: str) -> PlaybackResult:
        pose = self._repository.get_robot_pose(pose_id)
        step = SequenceStepSnapshot(
            robot_pose_id=pose.id,
            joints=tuple(sorted(pose.joints.items())),
            hold_ms=0,
            transition_ms=300,
        )
        enable_stabilization = getattr(
            self._simulator, "enable_stabilized_preview", None
        )
        if callable(enable_stabilization):
            enable_stabilization(ttl_seconds=1.0)

        self.output_mode = OutputMode.SIMULATOR
        await self._dispatcher(self._commands_for(step), True)
        self.dispatch_count += 1
        return PlaybackResult("completed", 1)

    async def preview_sequence(self, sequence_id: str) -> PlaybackResult:
        """Play a saved sequence immediately in the stabilized simulator.

        Simulator playback is stabilized and deliberately skips the slow
        physical stability preflight, whether started directly or by a trigger.
        Live-robot playback still uses the strict validator in :meth:`play`.
        """
        async with self._playback_lock:
            return await self._preview_sequence_locked(sequence_id)

    async def _preview_sequence_locked(self, sequence_id: str) -> PlaybackResult:
        snapshot = self._snapshot(sequence_id)
        preview_seconds = max(
            1.0,
            sum(step.transition_ms + step.hold_ms for step in snapshot.steps) / 1000,
        ) + 0.5
        enable_stabilization = getattr(
            self._simulator, "enable_stabilized_preview", None
        )
        if callable(enable_stabilization):
            enable_stabilization(ttl_seconds=preview_seconds)

        self.output_mode = OutputMode.SIMULATOR
        for step in snapshot.steps:
            await self._dispatcher(self._commands_for(step), True)
            self.dispatch_count += 1
            await self._sleeper(step.hold_ms / 1000)
        return PlaybackResult("completed", len(snapshot.steps))

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

    def _validate_snapshot(
        self,
        snapshot: SequenceSnapshot,
        *,
        initial: dict[str, float] | None = None,
    ) -> SequenceSafetyReport:
        result = validate_motion_path(
            self._simulator,
            [step.joint_targets() for step in snapshot.steps],
            f"studio sequence {snapshot.id}",
            initial=initial,
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
