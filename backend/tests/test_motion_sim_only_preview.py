"""Contracts for safety-checked simulator-only live pose mirroring."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes import motion
from app.robot.angle_utils import rad_to_servo_units
from app.schemas.requests import MoveRequest, ServoMove
from app.state import state


@pytest.fixture(autouse=True)
def _reset_state():
    class _Simulator:
        def get_all_joint_states(self) -> dict[str, float]:
            return {}

    previous_simulator = state.simulator
    previous_dispatcher = state.sim_dispatcher
    previous_collision_checker = state.collision_checker
    previous_stability_checker = state.stability_checker
    state.simulator = _Simulator()
    state.sim_dispatcher = object()
    state.collision_checker = None
    state.stability_checker = None
    yield
    state.simulator = previous_simulator
    state.sim_dispatcher = previous_dispatcher
    state.collision_checker = previous_collision_checker
    state.stability_checker = previous_stability_checker


def test_move_can_be_forced_to_simulator_and_returns_applied_safe_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    safe_targets = {"l_sho_pitch": 0.25}
    safety = {
        "fall_blocked": False,
        "collision_clamped": True,
        "safe_fraction": 0.6,
        "bad_pairs": ["arm<->torso"],
        "head_z": 0.5,
        "threshold_z": 0.3,
    }
    dispatch_modes: list[bool | None] = []

    monkeypatch.setattr(
        motion,
        "collision_checked_targets",
        lambda *_args, **_kwargs: (safe_targets, safety),
    )

    async def record_dispatch(_commands, sim_only=None) -> None:
        dispatch_modes.append(sim_only)

    monkeypatch.setattr(motion, "dispatch_servo_commands", record_dispatch)

    response = asyncio.run(
        motion.demo_move(
            MoveRequest(
                moves=[ServoMove(servo_id=13, position=600, duration_ms=120)],
                sim_only=True,
            )
        )
    )

    assert dispatch_modes == [True]
    assert response["status"] == "done"
    assert response["targets"] == safe_targets
    assert response["safety"] == safety


def test_move_request_cannot_force_hardware_dispatch() -> None:
    with pytest.raises(ValidationError):
        MoveRequest(moves=[], sim_only=False)


def test_fall_blocked_move_dispatches_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatch_count = 0

    monkeypatch.setattr(
        motion,
        "collision_checked_targets",
        lambda *_args, **_kwargs: (
            {"l_knee": 0.2},
            {
                "fall_blocked": True,
                "collision_clamped": False,
                "safe_fraction": 0.0,
                "bad_pairs": [],
            },
        ),
    )

    async def record_dispatch(_commands, sim_only=None) -> None:
        nonlocal dispatch_count
        dispatch_count += 1

    monkeypatch.setattr(motion, "dispatch_servo_commands", record_dispatch)

    response = asyncio.run(
        motion.demo_move(
            MoveRequest(
                moves=[ServoMove(servo_id=13, position=600, duration_ms=120)],
                sim_only=True,
            )
        )
    )

    assert response["status"] == "blocked"
    assert response["count"] == 0
    assert dispatch_count == 0


def test_missing_simulator_returns_service_unavailable() -> None:
    state.simulator = None

    with pytest.raises(HTTPException) as error:
        asyncio.run(motion.demo_move(MoveRequest(moves=[], sim_only=True)))

    assert error.value.status_code == 503


def test_live_preview_limits_abrupt_leg_changes() -> None:
    current = {
        "l_knee": 0.9,
        "r_knee": -0.9,
        "l_sho_pitch": 0.0,
    }
    target = {
        "l_knee": 1.5,
        "r_knee": -1.5,
        "l_sho_pitch": 1.0,
    }

    limited, changed = motion._limit_live_leg_step(current, target)

    assert changed is True
    assert limited["l_knee"] == pytest.approx(0.98)
    assert limited["r_knee"] == pytest.approx(-0.98)
    assert limited["l_sho_pitch"] == 1.0


def test_gentle_live_preview_limits_abrupt_arm_and_leg_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Simulator:
        def get_all_joint_states(self) -> dict[str, float]:
            return {"l_sho_pitch": 0.0, "l_knee": 0.0}

        def get_dynamics_state(self) -> dict[str, list[float]]:
            return {"qpos": [], "qvel": []}

    state.simulator = _Simulator()
    monkeypatch.setattr(
        motion,
        "collision_checked_targets",
        lambda _simulator, targets, _source, **_kwargs: (
            targets,
            {
                "fall_blocked": False,
                "collision_clamped": False,
                "safe_fraction": 1.0,
                "bad_pairs": [],
            },
        ),
    )

    async def ignore_dispatch(_commands, sim_only=None) -> None:
        assert sim_only is True

    monkeypatch.setattr(motion, "dispatch_servo_commands", ignore_dispatch)

    response = asyncio.run(
        motion.demo_move(
            MoveRequest(
                moves=[
                    ServoMove(
                        servo_id=13,
                        position=rad_to_servo_units(1.0),
                        duration_ms=220,
                    ),
                    ServoMove(
                        servo_id=5,
                        position=rad_to_servo_units(1.0),
                        duration_ms=220,
                    ),
                ],
                sim_only=True,
                gentle=True,
            )
        )
    )

    assert response["targets"]["l_sho_pitch"] == pytest.approx(0.08)
    assert response["targets"]["l_knee"] == pytest.approx(0.08)
    assert response["safety"]["rate_limited"] is True


def test_stabilized_preview_dispatches_raw_targets_without_safety_reduction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Simulator:
        stabilization_seconds: float | None = None

        def get_all_joint_states(self) -> dict[str, float]:
            return {"l_sho_pitch": 0.0}

        def enable_stabilized_preview(self, ttl_seconds: float) -> None:
            self.stabilization_seconds = ttl_seconds

    simulator = _Simulator()
    state.simulator = simulator

    def reject_safety_check(*_args, **_kwargs):
        raise AssertionError("direct stabilized preview must bypass predictive safety")

    monkeypatch.setattr(motion, "collision_checked_targets", reject_safety_check)

    dispatched = []

    async def record_dispatch(commands, sim_only=None) -> None:
        assert sim_only is True
        dispatched.extend(commands)

    monkeypatch.setattr(motion, "dispatch_servo_commands", record_dispatch)

    response = asyncio.run(
        motion.demo_move(
            MoveRequest(
                moves=[
                    ServoMove(
                        servo_id=13,
                        position=rad_to_servo_units(1.0),
                        duration_ms=220,
                    )
                ],
                sim_only=True,
                stabilized_preview=True,
            )
        )
    )

    assert response["status"] == "done"
    assert response["targets"]["l_sho_pitch"] == pytest.approx(1.0, abs=0.01)
    assert response["safety"] == {
        "fall_blocked": False,
        "collision_clamped": False,
        "rate_limited": False,
        "safe_fraction": 1.0,
        "bad_pairs": [],
        "head_z": None,
        "threshold_z": None,
    }
    assert simulator.stabilization_seconds == pytest.approx(1.0)
    assert len(dispatched) == 1


def test_stabilized_preview_requires_simulator_only_mode() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            motion.demo_move(
                MoveRequest(moves=[], stabilized_preview=True)
            )
        )

    assert error.value.status_code == 400


def test_live_mirror_checks_actual_duration_and_live_balance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dynamics = {
        "qpos": [0.0, 0.0, 0.31, 1.0, 0.0, 0.0, 0.0],
        "qvel": [0.03, 0.0, -0.02, 0.0, 0.1, 0.0],
        "ctrl": [0.2, -0.1],
    }

    class _Simulator:
        def get_all_joint_states(self) -> dict[str, float]:
            return {"l_sho_pitch": 0.0}

        def get_dynamics_state(self) -> dict[str, list[float]]:
            return dynamics

    class _StabilityChecker:
        def __init__(self) -> None:
            self.received: dict[str, object] = {}

        def check_fall(self, targets, current, **kwargs):
            self.received = {"targets": targets, "current": current, **kwargs}
            return {"fell": False, "head_z": 0.34, "threshold_z": 0.25}

    checker = _StabilityChecker()
    state.simulator = _Simulator()
    state.stability_checker = checker

    async def ignore_dispatch(_commands, sim_only=None) -> None:
        pass

    monkeypatch.setattr(motion, "dispatch_servo_commands", ignore_dispatch)
    asyncio.run(
        motion.demo_move(
            MoveRequest(
                moves=[ServoMove(servo_id=13, position=520, duration_ms=220)],
                sim_only=True,
                gentle=True,
            )
        )
    )

    assert checker.received["transition_seconds"] == pytest.approx(0.22)
    assert checker.received["dynamics_state"] == dynamics


def test_reset_waits_for_in_flight_live_move(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []

    class _Simulator:
        def get_all_joint_states(self) -> dict[str, float]:
            return {"l_sho_pitch": 0.0}

        def get_dynamics_state(self) -> dict[str, list[float]]:
            return {"qpos": [], "qvel": [], "ctrl": []}

        def reset_pose(self) -> None:
            order.append("reset")

    state.simulator = _Simulator()
    monkeypatch.setattr(
        motion,
        "collision_checked_targets",
        lambda _simulator, targets, _source, **_kwargs: (
            targets,
            {
                "fall_blocked": False,
                "collision_clamped": False,
                "safe_fraction": 1.0,
                "bad_pairs": [],
            },
        ),
    )

    async def exercise_race() -> None:
        dispatch_started = asyncio.Event()
        finish_dispatch = asyncio.Event()

        async def delayed_dispatch(_commands, sim_only=None) -> None:
            order.append("move-start")
            dispatch_started.set()
            await finish_dispatch.wait()
            order.append("move-end")

        monkeypatch.setattr(motion, "dispatch_servo_commands", delayed_dispatch)
        move_task = asyncio.create_task(
            motion.demo_move(
                MoveRequest(
                    moves=[ServoMove(servo_id=13, position=600, duration_ms=220)],
                    sim_only=True,
                    gentle=True,
                )
            )
        )
        await dispatch_started.wait()
        reset_task = asyncio.create_task(motion.reset_pose(sim_only=True))
        await asyncio.sleep(0)
        assert order == ["move-start"]

        finish_dispatch.set()
        await asyncio.gather(move_task, reset_task)

    asyncio.run(exercise_race())
    assert order == ["move-start", "move-end", "reset"]
