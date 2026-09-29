"""Tests for FollowSafetyGate — the stateful adapter that applies the CBF
safety filter to the live-follow mimicry stream (Phase 2 of
docs/cbf-whole-body-progress.md).

Uses the real AiNex model (module-scoped, since constructing a
SafetyFilter runs a real ~0.1s physics settle), matching this project's
established no-mocking-MuJoCo pattern for sim-facing code.

The values below are empirically found, not guessed — the same
_UNSAFE_HIP_ROLL / _SAFE_ARM_PITCH used by test_safety_filter.py, for
the same reasons documented there.
"""

from __future__ import annotations

import pytest

from app.balance.safety_filter import FollowSafetyGate, SafetyFilter

_UNSAFE_HIP_ROLL = 0.5
_SAFE_ARM_PITCH = 0.5


@pytest.fixture(scope="module")
def shared_filter() -> SafetyFilter:
    return SafetyFilter()


@pytest.fixture
def gate(shared_filter) -> FollowSafetyGate:
    # A fresh gate per test (cheap — reuses the one settled filter) so
    # each test starts from the standing baseline with zeroed counters.
    return FollowSafetyGate(shared_filter)


class TestPassThrough:
    def test_safe_arm_target_passes_through_unchanged(self, gate):
        targets = {"l_sho_pitch": _SAFE_ARM_PITCH}
        safe, intervened = gate.filter_targets(targets)
        assert safe == targets
        assert intervened is False
        assert gate.intervention_count == 0

    def test_joints_the_model_does_not_have_pass_through_untouched(self, gate):
        """Grippers and anything else absent from the MuJoCo model must
        survive the gate verbatim — the filter only reasons about hinge
        joints it knows, and must not silently drop the rest."""
        targets = {"l_sho_pitch": 0.1, "not_a_real_joint": 0.42}
        safe, _intervened = gate.filter_targets(targets)
        assert safe["not_a_real_joint"] == 0.42

    def test_empty_targets_are_returned_as_is(self, gate):
        safe, intervened = gate.filter_targets({})
        assert safe == {}
        assert intervened is False


class TestIntervention:
    def test_unsafe_target_is_scaled_back_and_counted(self, gate):
        safe, intervened = gate.filter_targets({"r_hip_roll": _UNSAFE_HIP_ROLL})
        assert intervened is True
        assert gate.intervention_count == 1
        # Held back from the unsafe request, but still moved toward it —
        # the point of a filter rather than an all-or-nothing block.
        assert 0.0 < safe["r_hip_roll"] < _UNSAFE_HIP_ROLL

    def test_margin_is_reported_after_filtering(self, gate):
        gate.filter_targets({"l_sho_pitch": _SAFE_ARM_PITCH})
        assert gate.last_margin is not None
        assert gate.last_margin > 0


class TestStatefulness:
    def test_seeds_from_standing_not_from_an_empty_pose(self, shared_filter, gate):
        """The first frame must interpolate from the real standing pose.

        Regression guard for a subtle failure mode: if the gate started
        from an empty "current" dict, SafetyFilter.check_trajectory's own
        convention (a joint in target but absent from current is treated
        as not moving) would make the very first frame — the big 800ms
        seed move from STAND to the human's first detected pose — pass
        through entirely unchecked.
        """
        assert gate.current_joints == shared_filter.settled_joint_values()
        safe, intervened = gate.filter_targets({"r_hip_roll": _UNSAFE_HIP_ROLL})
        assert intervened is True
        assert safe["r_hip_roll"] < _UNSAFE_HIP_ROLL

    def test_tracks_commanded_pose_across_frames(self, gate):
        """Frame N+1 must interpolate from what frame N actually
        commanded, not from standing — otherwise every frame re-checks
        the same journey from stand and the robot can creep past a limit
        one small, individually-safe step at a time."""
        gate.filter_targets({"l_sho_pitch": _SAFE_ARM_PITCH})
        assert gate.current_joints["l_sho_pitch"] == pytest.approx(_SAFE_ARM_PITCH)

    def test_scaled_back_value_becomes_the_new_current(self, gate):
        safe, _ = gate.filter_targets({"r_hip_roll": _UNSAFE_HIP_ROLL})
        assert gate.current_joints["r_hip_roll"] == pytest.approx(safe["r_hip_roll"])

    def test_joints_absent_from_a_frame_keep_their_last_commanded_value(self, gate):
        """compute_joint_targets emits only confidently-tracked joints, so
        a joint can vanish for a frame; its real commanded position must
        persist rather than silently reverting to stand."""
        gate.filter_targets({"l_sho_pitch": _SAFE_ARM_PITCH})
        gate.filter_targets({"head_pan": 0.1})
        assert gate.current_joints["l_sho_pitch"] == pytest.approx(_SAFE_ARM_PITCH)

    def test_reset_restores_standing_and_clears_counters(self, shared_filter, gate):
        gate.filter_targets({"r_hip_roll": _UNSAFE_HIP_ROLL})
        assert gate.intervention_count == 1
        gate.reset()
        assert gate.intervention_count == 0
        assert gate.current_joints == shared_filter.settled_joint_values()


class TestFailOpen:
    def test_a_filter_failure_passes_targets_through_rather_than_blocking(self, gate):
        """This gate is a new advisory layer bolted onto a working demo
        path. If it breaks, live follow must keep working — an unfiltered
        move is the pre-existing behavior, a dead follow loop is a
        regression."""

        class _Boom:
            def check_trajectory(self, *_a, **_kw):
                raise RuntimeError("filter exploded")

        gate._filter = _Boom()
        targets = {"l_sho_pitch": 0.3}
        safe, intervened = gate.filter_targets(targets)
        assert safe == targets
        assert intervened is False
        assert gate.failure_count == 1
