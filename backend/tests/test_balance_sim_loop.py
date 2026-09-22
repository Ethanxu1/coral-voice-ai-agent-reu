"""Tests for SimBalanceLoop (backend/app/balance/sim_loop.py).

Focused on _baseline_rad's construction — the bug found 2026-09-22 (the
sim-side twin of balance_loop.py's 2026-09-21 r_ank_roll baseline fix,
.agents/fixes/2026-09-21-balance-loop-baseline-rad.md). Doesn't spin up
live physics (start_viewer()) since the bug is fully captured by the
constructed state itself, not by anything that only shows up over time.
"""

import pytest

from app.balance.controller import BalanceGains
from app.balance.sim_loop import SimBalanceLoop
from app.robot.hardware_angle_utils import HW_STAND_RAD
from app.simulator import AiNexSimulator


@pytest.fixture(scope="module")
def simulator() -> AiNexSimulator:
    return AiNexSimulator()


class TestBaselineRad:
    def test_r_ank_roll_baseline_matches_its_true_stand_keyframe_value(self, simulator):
        """r_ank_roll's stand keyframe value is -0.0698 rad, not 0 — a
        real asymmetry (see HW_STAND_RAD's own docstring: it must match
        ainex.xml's stand keyframe joint-for-joint). Before the fix,
        SimBalanceLoop assumed 0.0 for every roll joint, which silently
        commanded r_ank_roll to the wrong resting position even when the
        controller's own computed offset was exactly zero."""
        loop = SimBalanceLoop(simulator)
        assert loop._baseline_rad["r_ank_roll"] == HW_STAND_RAD["r_ank_roll"]
        assert loop._baseline_rad["r_ank_roll"] != 0.0

    def test_l_ank_roll_and_hip_roll_joints_correctly_default_to_zero(self, simulator):
        """These joints have no HW_STAND_RAD entry, which (per that
        table's own convention) means their true stand-keyframe value IS
        0.0 — not an oversight, so the fix must not give them a nonzero
        baseline they were never supposed to have."""
        loop = SimBalanceLoop(simulator)
        assert loop._baseline_rad["l_ank_roll"] == 0.0
        assert loop._baseline_rad["l_hip_roll"] == 0.0
        assert loop._baseline_rad["r_hip_roll"] == 0.0

    def test_baseline_rad_covers_exactly_the_four_roll_joints(self, simulator):
        loop = SimBalanceLoop(simulator)
        assert set(loop._baseline_rad.keys()) == {
            "l_ank_roll", "r_ank_roll", "l_hip_roll", "r_hip_roll",
        }

    def test_custom_gains_do_not_affect_the_baseline(self, simulator):
        """Sanity check: _baseline_rad reflects the robot's own stand
        keyframe, not anything derived from BalanceGains — passing custom
        gains must not change it."""
        default_loop = SimBalanceLoop(simulator)
        custom_loop = SimBalanceLoop(simulator, gains=BalanceGains(ankle_kp=1.0))
        assert custom_loop._baseline_rad == default_loop._baseline_rad
