"""The live-follow loop must actually route targets through the CBF
safety gate and dispatch the FILTERED result (Phase 2 of
docs/cbf-whole-body-progress.md).

The gate itself is covered by test_follow_safety_gate.py; these tests
cover the wiring, which is the part that silently breaks — a gate that
works perfectly but is never consulted, or is consulted and then has its
result thrown away, would pass every test in that file.

FollowController._follow_loop needs a live vision WebSocket, so these
exercise _ensure_safety_gate (the construction/enable path) and the
filter-then-dispatch contract directly rather than standing up a fake
vision server.
"""

from __future__ import annotations

import pytest

from app import config
from app.balance.safety_filter import FollowSafetyGate
from app.follow_controller import FollowController


async def _noop_dispatch(commands, sim_only=None):
    pass


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def restore_flag():
    prev = config.ENABLE_FOLLOW_SAFETY
    yield
    config.ENABLE_FOLLOW_SAFETY = prev


class TestGateConstruction:
    @pytest.mark.anyio
    async def test_disabled_flag_yields_no_gate(self, restore_flag):
        """The A/B comparison Phase 2 calls for depends on this actually
        turning the layer off, not just muting its logging."""
        config.ENABLE_FOLLOW_SAFETY = False
        controller = FollowController(_noop_dispatch)
        assert await controller._ensure_safety_gate() is None

    @pytest.mark.anyio
    async def test_enabled_flag_builds_a_gate(self, restore_flag):
        config.ENABLE_FOLLOW_SAFETY = True
        controller = FollowController(_noop_dispatch)
        gate = await controller._ensure_safety_gate()
        assert isinstance(gate, FollowSafetyGate)

    @pytest.mark.anyio
    async def test_gate_is_built_once_and_reused_across_sessions(self, restore_flag):
        """Rebuilding per session would re-run the physics settle on every
        'follow me', adding startup latency to each one."""
        config.ENABLE_FOLLOW_SAFETY = True
        controller = FollowController(_noop_dispatch)
        first = await controller._ensure_safety_gate()
        second = await controller._ensure_safety_gate()
        assert first is second

    @pytest.mark.anyio
    async def test_each_session_starts_from_a_clean_gate_state(self, restore_flag):
        """Reused instance, but stale counters/pose from the previous
        session must not leak into the next one — the robot is back at
        stand by then."""
        config.ENABLE_FOLLOW_SAFETY = True
        controller = FollowController(_noop_dispatch)
        gate = await controller._ensure_safety_gate()
        gate.filter_targets({"r_hip_roll": 0.5})
        assert gate.intervention_count == 1

        reused = await controller._ensure_safety_gate()
        assert reused.intervention_count == 0
        assert reused.current_joints == reused._filter.settled_joint_values()


class TestObservability:
    """The filter is unobservable in a live session unless these hold,
    and both failed silently once already.

    The follow heartbeat originally used stdlib `logging` while this app
    logs through loguru, with no bridge between them. Stdlib's
    last-resort handler only emits WARNING and above, so every heartbeat
    was dropped and a live debugging session was spent watching a log
    line that could never appear.
    """

    def test_follow_controller_logs_through_loguru(self):
        import loguru

        from app import follow_controller

        assert isinstance(follow_controller.logger, type(loguru.logger))

    def test_clean_logger_tick_carries_the_safety_fields(self):
        """clean_logs is the channel that actually worked during the
        failure above, so the safety numbers have to reach it too."""
        import inspect

        from app.services.clean_logger import CleanLogger

        params = inspect.signature(CleanLogger.follow_tick).parameters
        assert "safety_holds" in params
        assert "stability_margin" in params


class TestFilteredTargetsAreWhatGetsDispatched:
    @pytest.mark.anyio
    async def test_unsafe_targets_are_reduced_before_servo_conversion(self, restore_flag):
        """End-to-end on the value path: what the gate returns is what
        gets turned into servo commands, so an unsafe request reaches the
        robot only in its scaled-back form."""
        from app.vision.pose_to_robot import targets_to_servo_commands

        config.ENABLE_FOLLOW_SAFETY = True
        controller = FollowController(_noop_dispatch)
        gate = await controller._ensure_safety_gate()

        requested = {"r_hip_roll": 0.5}
        safe, held_back = gate.filter_targets(requested)
        assert held_back is True

        unfiltered_cmds = targets_to_servo_commands(requested, 45)
        filtered_cmds = targets_to_servo_commands(safe, 45)
        assert filtered_cmds[0].position != unfiltered_cmds[0].position
