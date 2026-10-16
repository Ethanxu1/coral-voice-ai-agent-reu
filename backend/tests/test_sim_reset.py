"""Contracts for simulator-only recovery to the standing pose."""

from __future__ import annotations

import asyncio

import pytest

from app.api.routes import motion
from app.state import state


def test_sim_only_reset_never_dispatches_to_hardware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Simulator:
        reset_count = 0

        def reset_pose(self) -> None:
            self.reset_count += 1

        def get_stand_joint_positions(self) -> dict[str, float]:
            return {"l_knee": 0.2}

    simulator = _Simulator()
    previous_simulator = state.simulator
    previous_hardware = state.hardware_dispatcher
    state.simulator = simulator
    state.hardware_dispatcher = object()
    hardware_dispatches = 0

    async def record_dispatch(*_args, **_kwargs) -> None:
        nonlocal hardware_dispatches
        hardware_dispatches += 1

    monkeypatch.setattr(motion, "dispatch_servo_commands", record_dispatch)
    try:
        response = asyncio.run(motion.reset_pose(sim_only=True))
    finally:
        state.simulator = previous_simulator
        state.hardware_dispatcher = previous_hardware

    assert response == {"status": "done"}
    assert simulator.reset_count == 1
    assert hardware_dispatches == 0
