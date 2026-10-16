"""Fixed-base simulator preview keeps the body upright while joints remain free."""

import numpy as np
import pytest

from app.simulator import mujoco_sim
from app.simulator.mujoco_sim import AiNexSimulator


def test_stabilized_preview_pins_only_the_floating_base() -> None:
    simulator = AiNexSimulator()
    simulator.enable_stabilized_preview(ttl_seconds=1.0)

    expected_base = simulator.data.qpos[:7].copy()
    joint_position = float(simulator.data.qpos[7]) + 0.2
    simulator.data.qpos[:3] += np.array([0.1, -0.1, -0.2])
    simulator.data.qpos[3:7] = np.array([0.5, 0.5, 0.5, 0.5])
    simulator.data.qvel[:6] = 1.0
    simulator.data.qpos[7] = joint_position

    with simulator._lock:
        simulator._pin_stabilized_preview_base_locked()

    np.testing.assert_allclose(simulator.data.qpos[:7], expected_base)
    np.testing.assert_allclose(simulator.data.qvel[:6], 0.0)
    assert simulator.data.qpos[7] == joint_position


def test_stabilized_preview_expires_and_stops_pinning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    simulator = AiNexSimulator()
    clock = iter((10.0, 10.5, 11.1))
    monkeypatch.setattr(mujoco_sim.time, "monotonic", lambda: next(clock))
    simulator.enable_stabilized_preview(ttl_seconds=1.0)

    simulator.data.qpos[0] += 0.2
    with simulator._lock:
        assert simulator._pin_stabilized_preview_base_locked() is True
    pinned_x = float(simulator.data.qpos[0])

    simulator.data.qpos[0] += 0.3
    with simulator._lock:
        assert simulator._pin_stabilized_preview_base_locked() is False
    assert simulator.data.qpos[0] == pytest.approx(pinned_x + 0.3)


def test_reset_clears_preview_lease_inside_the_atomic_stand_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    simulator = AiNexSimulator()
    simulator.data.qpos[0] = 0.4
    simulator.enable_stabilized_preview(ttl_seconds=10.0)
    old_pinned_x = float(simulator.data.qpos[0])
    original_apply_locked = simulator._apply_stand_keyframe_locked
    observed: dict[str, bool] = {}

    def inspect_atomic_reset(lift: float = 0.0) -> bool:
        unexpectedly_acquired = simulator._lock.acquire(blocking=False)
        if unexpectedly_acquired:
            simulator._lock.release()
        observed["lock_held"] = not unexpectedly_acquired
        observed["lease_cleared"] = simulator._stabilized_preview_until == 0.0
        return original_apply_locked(lift)

    monkeypatch.setattr(
        simulator,
        "_apply_stand_keyframe_locked",
        inspect_atomic_reset,
    )

    simulator.reset_pose()

    assert observed == {"lock_held": True, "lease_cleared": True}
    assert simulator.data.qpos[0] != pytest.approx(old_pinned_x)
    assert simulator.is_stabilized_preview_active() is False
