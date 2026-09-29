"""LegLiftController: lift a leg visibly during follow mode without falling.

Most tests drive the controller directly with explicit dt (fast,
deterministic). One physics test at the end checks the actual guarantee
through the full retargeting path.

Verified in simulation when written: 10/10 raise-hold-lower cycles on
both legs (20-60 deg raises) stay up with 3-6.6cm of foot clearance, and
48/48 still stay up under 50% leg-tracking dropout + 30% whole-frame
drops + jitter.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

from app.validation import JOINT_LIMITS
from app.vision.leg_lift_controller import (
    ANKLES,
    LIFT_SECONDS,
    RELEASE_SECONDS,
    SETTLE_SECONDS,
    SHIFT_RAD,
    SHIFT_SECONDS,
    LegLiftController,
    Phase,
    _rate,
)
from app.vision.pose_to_robot import _STAND_LEG_TARGETS
from app.robot.hardware_angle_utils import HW_STAND_RAD

DT = 0.05
STAND = dict(_STAND_LEG_TARGETS)


def _lifted(side: str, fraction: float = 0.8) -> dict[str, float]:
    """Unlimited retargeted legs with one leg raised by `fraction` of its
    hip travel, plus an arm joint to check pass-through."""
    d = dict(STAND)
    hp, kn = f"{side}_hip_pitch", f"{side}_knee"
    if side == "l":
        d[hp] = STAND[hp] - fraction * (STAND[hp] - JOINT_LIMITS[hp].min)
        d[kn] = STAND[kn] + fraction * (JOINT_LIMITS[kn].max - STAND[kn])
    else:
        d[hp] = STAND[hp] + fraction * (JOINT_LIMITS[hp].max - STAND[hp])
        d[kn] = STAND[kn] - fraction * (STAND[kn] - JOINT_LIMITS[kn].min)
    d["l_sho_pitch"] = 0.7
    return d


def _run(ctl: LegLiftController, desired: dict[str, float], seconds: float) -> dict[str, float]:
    out = {}
    for _ in range(int(round(seconds / DT))):
        out = ctl.update(desired, DT)
    return out


def _ankle_stand(j: str) -> float:
    return HW_STAND_RAD.get(j, 0.0)


class TestStanding:
    def test_a_standing_person_leaves_everything_at_stand(self):
        ctl = LegLiftController()
        out = _run(ctl, dict(STAND), 2.0)
        assert ctl.phase is Phase.IDLE
        for j, v in STAND.items():
            assert out[j] == pytest.approx(v, abs=1e-6), j
        for a in ANKLES:
            assert out[a] == pytest.approx(_ankle_stand(a), abs=1e-6), a

    def test_non_leg_joints_pass_through(self):
        ctl = LegLiftController()
        out = ctl.update({**STAND, "l_sho_pitch": 0.7, "head_pan": 0.3}, DT)
        assert out["l_sho_pitch"] == 0.7
        assert out["head_pan"] == 0.3


class TestSequence:
    @pytest.mark.parametrize("side,sign", [("l", -1), ("r", +1)])
    def test_weight_shifts_toward_the_support_foot(self, side, sign):
        """Lifting the left leg moves weight onto the right foot, which is
        a NEGATIVE ankle delta (measured); the right leg mirrors it."""
        ctl = LegLiftController()
        out = _run(ctl, _lifted(side), SHIFT_SECONDS + 0.2)
        for a in ANKLES:
            assert out[a] - _ankle_stand(a) == pytest.approx(sign * SHIFT_RAD, abs=1e-6)

    def test_swing_foot_stays_planted_until_the_weight_has_settled(self):
        """The core of the fix: lift and shift together topples the robot."""
        ctl = LegLiftController()
        desired = _lifted("l")
        out = _run(ctl, desired, SHIFT_SECONDS + SETTLE_SECONDS - 0.2)
        assert ctl.phase in (Phase.SHIFTING, Phase.SETTLING)
        assert out["l_hip_pitch"] == pytest.approx(STAND["l_hip_pitch"], abs=1e-6)
        assert out["l_knee"] == pytest.approx(STAND["l_knee"], abs=1e-6)

    def test_leg_lifts_after_settling(self):
        ctl = LegLiftController()
        out = _run(ctl, _lifted("l"), SHIFT_SECONDS + SETTLE_SECONDS + LIFT_SECONDS + 0.5)
        assert ctl.phase is Phase.LIFTING
        assert out["l_hip_pitch"] < STAND["l_hip_pitch"] - 0.3

    def test_support_leg_and_hip_rolls_hold_stand_during_a_lift(self):
        ctl = LegLiftController()
        desired = _lifted("l")
        desired["r_hip_pitch"] += 0.2
        desired["l_hip_roll"] = 0.2
        out = _run(ctl, desired, SHIFT_SECONDS + SETTLE_SECONDS + LIFT_SECONDS + 0.5)
        for j in ("r_hip_pitch", "r_knee", "l_hip_roll", "r_hip_roll"):
            assert out[j] == pytest.approx(STAND[j], abs=1e-6), j

    def test_returns_to_stand_when_the_person_lowers_the_leg(self):
        ctl = LegLiftController()
        _run(ctl, _lifted("l"), 4.0)
        out = _run(ctl, dict(STAND), 5.0)
        assert ctl.phase is Phase.IDLE
        for a in ANKLES:
            assert out[a] == pytest.approx(_ankle_stand(a), abs=1e-6)
        assert out["l_hip_pitch"] == pytest.approx(STAND["l_hip_pitch"], abs=1e-6)


class TestNothingSteps:
    def test_every_leg_and_ankle_joint_is_rate_limited(self):
        """Single-frame jumps are what toppled an earlier version: a shift
        finished in 0.3s instead of 0.9s and the momentum carried the
        robot over while both feet were still down."""
        ctl = LegLiftController()
        prev = ctl.update(dict(STAND), DT)
        script = [(_lifted("l"), 5.0), (dict(STAND), 4.0), (_lifted("r"), 5.0), (dict(STAND), 4.0)]
        for desired, seconds in script:
            for _ in range(int(seconds / DT)):
                out = ctl.update(desired, DT)
                for j in list(STAND) + list(ANKLES):
                    assert abs(out[j] - prev[j]) <= _rate(j) * DT + 1e-9, j
                prev = out

    def test_ankle_shift_takes_the_verified_time(self):
        assert _rate("l_ank_roll") == pytest.approx(SHIFT_RAD / SHIFT_SECONDS)


class TestVisionDropouts:
    def test_a_brief_dropout_does_not_abort_a_lift(self):
        """Dropped or knee-gated frames retarget the legs to stand, which
        reads as 'leg lowered'. One live session lost the person on ~half
        of all frames."""
        ctl = LegLiftController()
        _run(ctl, _lifted("l"), 4.0)
        assert ctl.phase is Phase.LIFTING
        _run(ctl, dict(STAND), RELEASE_SECONDS - 2 * DT)
        ctl.update(_lifted("l"), DT)
        assert ctl.phase is Phase.LIFTING

    def test_leg_coming_back_up_while_lowering_resumes_the_lift(self):
        ctl = LegLiftController()
        _run(ctl, _lifted("l"), 4.0)
        _run(ctl, dict(STAND), RELEASE_SECONDS + 0.1)
        assert ctl.phase is Phase.LOWERING
        ctl.update(_lifted("l"), DT)
        assert ctl.phase is Phase.LIFTING


# ── Physics: the actual guarantee ─────────────────────────────────────────


@pytest.mark.parametrize("person_side,robot_foot", [("r", "l_foot1"), ("l", "r_foot1")])
def test_robot_lifts_a_leg_and_stays_up(person_side, robot_foot):
    """Person raises a leg 45 deg, holds, lowers. Through the real
    retargeting at 20Hz, the robot must lift its foot visibly and never
    fall. Falling is checked on every frame."""
    mujoco = pytest.importorskip("mujoco")
    sys.path.insert(0, str(Path(__file__).parent / "vision"))
    from test_pose_to_robot import _build_body  # noqa: E402

    from app.balance.sim_source import read_attitude
    from app.simulator.mujoco_sim import AiNexSimulator
    from app.vision.pose_to_robot import compute_joint_targets

    def body(deg):
        if deg <= 0:
            return _build_body()
        dy, dz = 0.4 * math.cos(math.radians(deg)), -0.4 * math.sin(math.radians(deg))
        x = -0.1 if person_side == "r" else 0.1
        k, a, i = (("r_knee", "r_ankle", "img_r_knee") if person_side == "r"
                   else ("l_knee", "l_ankle", "img_l_knee"))
        return _build_body(**{k: (x, dy, dz), a: (x, dy + 0.4, dz),
                              i: (0.45 if person_side == "r" else 0.55, 0.75)})

    sim = AiNexSimulator()
    for _ in range(1250):
        mujoco.mj_step(sim.model, sim.data)
    gid = mujoco.mj_name2id(sim.model, mujoco.mjtObj.mjOBJ_GEOM, robot_foot)
    z0 = float(sim.data.geom_xpos[gid][2])
    h0 = float(sim.data.subtree_com[0][2])
    ctl = LegLiftController()

    frames = ([45 * (k + 1) / 20 for k in range(20)] + [45] * 80
              + [45 * (1 - (k + 1) / 20) for k in range(20)] + [0] * 60)
    peak = 0.0
    for n, deg in enumerate(frames):
        cmd = ctl.update(compute_joint_targets(body(deg), None, leg_travel_limit=1.0), DT)
        for j, v in cmd.items():
            try:
                sim.set_joint_position(j, v)
            except ValueError:
                pass
        for _ in range(25):
            mujoco.mj_step(sim.model, sim.data)
        att = read_attitude(sim.model, sim.data)
        h = float(sim.data.subtree_com[0][2])
        assert abs(math.degrees(att.roll_rad)) < 30, f"fell (roll) at {n * DT:.2f}s"
        assert abs(math.degrees(att.pitch_rad)) < 30, f"fell (pitch) at {n * DT:.2f}s"
        assert h > h0 * 0.75, f"collapsed at {n * DT:.2f}s"
        peak = max(peak, float(sim.data.geom_xpos[gid][2]) - z0)

    assert peak > 0.03, f"foot only rose {peak * 100:.1f}cm -- not a visible lift"
    assert ctl.phase is Phase.IDLE
