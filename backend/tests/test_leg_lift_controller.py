"""LegLiftController: lift a leg during follow mode, upright, without falling.

Most tests drive the controller directly with explicit dt (fast,
deterministic). The physics tests at the end check the actual
guarantees through the full retargeting path: stays up, torso stays
upright, both legs lift to the same height, and the robot trails the
person by well under a second.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

from app.robot.hardware_angle_utils import HW_STAND_RAD
from app.validation import JOINT_LIMITS
from app.vision.leg_lift_controller import (
    ANKLE_SHIFT,
    ANKLES,
    DECISION_TAU,
    HIP_RATIO,
    HIP_ROLLS,
    IDLE_TRAVEL,
    LOWER_RATE,
    MAX_DT,
    ONSET_SECONDS,
    RELEASE_SECONDS,
    SHIFT_SECONDS,
    LegLiftController,
    Phase,
    _rate,
    _reach,
)
from app.vision.pose_to_robot import _STAND_LEG_TARGETS

DT = 0.05
STAND = dict(_STAND_LEG_TARGETS)
SHIFTED_BY = ONSET_SECONDS + SHIFT_SECONDS + 3 * DT


def _stand(j: str) -> float:
    return STAND[j] if j in STAND else HW_STAND_RAD.get(j, 0.0)


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


def _run(ctl, desired, seconds, dt=DT):
    out = {}
    for _ in range(int(round(seconds / dt))):
        out = ctl.update(desired, dt)
    return out


class TestStanding:
    def test_a_standing_person_leaves_everything_at_stand(self):
        ctl = LegLiftController()
        out = _run(ctl, dict(STAND), 2.0)
        assert ctl.phase is Phase.IDLE
        for j in list(STAND) + list(ANKLES):
            assert out[j] == pytest.approx(_stand(j), abs=1e-6), j

    def test_non_leg_joints_pass_through(self):
        out = LegLiftController().update({**STAND, "l_sho_pitch": 0.7, "head_pan": 0.3}, DT)
        assert out["l_sho_pitch"] == 0.7
        assert out["head_pan"] == 0.3

    def test_a_single_jittery_frame_does_not_slide_the_hips(self):
        """Detection is deliberately sensitive, so onset needs confirming:
        without it vision jitter alone set off ~6 hip slides per 20s."""
        ctl = LegLiftController()
        ctl.update(_lifted("l", 0.2), DT)
        ctl.update(dict(STAND), DT)
        assert ctl.phase is Phase.IDLE


class TestUprightShift:
    @pytest.mark.parametrize("side,sign", [("l", -1), ("r", +1)])
    def test_hips_slide_over_the_support_foot(self, side, sign):
        """Lifting the left leg puts weight on the right foot -- a NEGATIVE
        delta (measured). Hips roll HIP_RATIO x the ankles the same way so
        the legs form a parallelogram and the torso stays vertical."""
        ctl = LegLiftController()
        out = _run(ctl, _lifted(side), SHIFTED_BY)
        for a in ANKLES:
            assert out[a] - _stand(a) == pytest.approx(sign * ANKLE_SHIFT, abs=1e-6)
        for h in HIP_ROLLS:
            assert out[h] - _stand(h) == pytest.approx(sign * HIP_RATIO * ANKLE_SHIFT, abs=1e-6)

    def test_no_partial_lift_before_a_lift_is_even_detected(self):
        """An unsupported partial lift starts the robot rolling; if dropped
        frames then delay the shift, the shift arrives against a moving
        body, overshoots and the robot falls the other way (traced). So
        before a lift is detected the leg barely moves at all."""
        ctl = LegLiftController()
        out = ctl.update(_lifted("l", 0.6), DT)
        assert ctl.phase is Phase.IDLE
        reach = STAND["l_hip_pitch"] - JOINT_LIMITS["l_hip_pitch"].min
        assert STAND["l_hip_pitch"] - out["l_hip_pitch"] <= IDLE_TRAVEL * reach + 1e-9

    def test_swing_foot_stays_planted_until_the_shift_arrives(self):
        """Shift and lift together topples the robot on both legs."""
        ctl = LegLiftController()
        _run(ctl, _lifted("l"), ONSET_SECONDS + DT)
        assert ctl.phase is Phase.SHIFTING
        out = ctl.update(_lifted("l"), DT)
        assert out["l_hip_pitch"] == pytest.approx(STAND["l_hip_pitch"], abs=1e-6)
        assert out["l_knee"] == pytest.approx(STAND["l_knee"], abs=1e-6)

    def test_no_settling_pause_once_shifted(self):
        """The upright shift needs no settle pause -- that is where most of
        the old ~2s delay went."""
        ctl = LegLiftController()
        _run(ctl, _lifted("l"), SHIFTED_BY)
        assert ctl.phase is Phase.LIFTING

    def test_support_leg_holds_its_stance_during_a_lift(self):
        ctl = LegLiftController()
        desired = _lifted("l")
        desired["r_hip_pitch"] += 0.2
        out = _run(ctl, desired, SHIFTED_BY + 1.0)
        for j in ("r_hip_pitch", "r_knee"):
            assert out[j] == pytest.approx(STAND[j], abs=1e-6), j

    def test_returns_to_stand_when_the_leg_is_lowered(self):
        ctl = LegLiftController()
        _run(ctl, _lifted("l"), 2.0)
        out = _run(ctl, dict(STAND), 3.0)
        assert ctl.phase is Phase.IDLE
        for j in list(STAND) + list(ANKLES):
            assert out[j] == pytest.approx(_stand(j), abs=1e-6), j


class TestNothingSteps:
    def test_every_leg_and_ankle_joint_is_rate_limited(self):
        ctl = LegLiftController()
        prev = ctl.update(dict(STAND), DT)
        script = [(_lifted("l"), 3.0), (dict(STAND), 3.0), (_lifted("r"), 3.0), (dict(STAND), 3.0)]
        for desired, seconds in script:
            for _ in range(int(seconds / DT)):
                out = ctl.update(desired, DT)
                for j in list(STAND) + list(ANKLES):
                    assert abs(out[j] - prev[j]) <= _rate(j) * DT + 1e-9, j
                prev = out

    def test_a_long_gap_does_not_turn_into_a_jump(self):
        """After dropped frames the next update sees a long dt; acting on
        all of it at once would be a step."""
        ctl = LegLiftController()
        prev = ctl.update(dict(STAND), DT)
        _run(ctl, _lifted("l"), ONSET_SECONDS + DT)
        prev = ctl.update(_lifted("l"), DT)
        out = ctl.update(_lifted("l"), 1.0)
        for j in ANKLES + HIP_ROLLS:
            assert abs(out[j] - prev[j]) <= _rate(j) * MAX_DT + 1e-9, j

    def test_shift_speed_is_sized_from_the_shift_not_the_joint_range(self):
        """Sizing by range once made a shift 3x too fast; the momentum
        toppled the robot with both feet still down."""
        assert _rate("l_ank_roll") == pytest.approx(ANKLE_SHIFT / SHIFT_SECONDS)


# Time for a lowered reading to be confirmed: the smoothed reading has to
# fall below LIFT_OFF (a few DECISION_TAU) and then stay there.
CONFIRM_LOWERED = 3 * DECISION_TAU + RELEASE_SECONDS + 3 * DT


class TestVisionDropouts:
    def test_a_dropped_frame_only_nudges_the_lifted_leg(self):
        """A dropped or knee-gated frame retargets legs to stand. Followed
        directly, a run of them pumped the lifted leg up and down and
        tipped the robot. Downward motion is rate-limited instead, and the
        next good frame restores the leg."""
        ctl = LegLiftController()
        before = _run(ctl, _lifted("l"), 2.0)
        assert ctl.phase is Phase.LIFTING
        dropped = ctl.update(dict(STAND), DT)
        assert ctl.phase is Phase.LIFTING
        moved = abs(dropped["l_hip_pitch"] - before["l_hip_pitch"])
        assert moved <= LOWER_RATE * _reach("l_hip_pitch") * DT + 1e-9
        restored = _run(ctl, _lifted("l"), 0.2)
        assert restored["l_hip_pitch"] == pytest.approx(before["l_hip_pitch"], abs=1e-6)

    def test_a_short_run_of_dropped_frames_does_not_end_the_lift(self):
        ctl = LegLiftController()
        _run(ctl, _lifted("l"), 2.0)
        _run(ctl, dict(STAND), 3 * DT)
        assert ctl.phase is Phase.LIFTING

    @pytest.mark.parametrize("lowered_for", [0.2, CONFIRM_LOWERED])
    def test_raising_the_leg_again_on_the_way_down_lifts_again(self, lowered_for):
        """Whether the lowering was still unconfirmed (0.2s) or already
        confirmed and the hips were sliding back, raising the leg again
        must end in a supported lift, not a stall or an unsupported one."""
        ctl = LegLiftController()
        _run(ctl, _lifted("l"), 2.0)
        _run(ctl, dict(STAND), lowered_for)
        out = _run(ctl, _lifted("l"), 1.5)
        assert ctl.phase is Phase.LIFTING
        assert out["l_hip_pitch"] < STAND["l_hip_pitch"] - 0.3
        for a in ANKLES:
            assert out[a] - _stand(a) == pytest.approx(-ANKLE_SHIFT, abs=1e-6)


# ── Physics: the actual guarantees ────────────────────────────────────────


def _physics_lift(person_side: str, deg: float = 45.0):
    """Person raises a leg over 0.6s, holds 3s, lowers. Returns
    (fell_at, worst |torso roll| deg, foot peak m, lag s)."""
    mujoco = pytest.importorskip("mujoco")
    sys.path.insert(0, str(Path(__file__).parent / "vision"))
    from test_pose_to_robot import _build_body  # noqa: E402

    from app.balance.sim_source import read_attitude
    from app.simulator.mujoco_sim import AiNexSimulator
    from app.vision.pose_to_robot import compute_joint_targets

    def body(d):
        if d <= 0:
            return _build_body()
        dy, dz = 0.4 * math.cos(math.radians(d)), -0.4 * math.sin(math.radians(d))
        x = -0.1 if person_side == "r" else 0.1
        k, a, i = (("r_knee", "r_ankle", "img_r_knee") if person_side == "r"
                   else ("l_knee", "l_ankle", "img_l_knee"))
        return _build_body(**{k: (x, dy, dz), a: (x, dy + 0.4, dz),
                              i: (0.45 if person_side == "r" else 0.55, 0.75)})

    robot_foot = "l_foot1" if person_side == "r" else "r_foot1"
    sim = AiNexSimulator()
    for _ in range(1250):
        mujoco.mj_step(sim.model, sim.data)
    gid = mujoco.mj_name2id(sim.model, mujoco.mjtObj.mjOBJ_GEOM, robot_foot)
    z0 = float(sim.data.geom_xpos[gid][2])
    h0 = float(sim.data.subtree_com[0][2])
    ctl = LegLiftController()
    frames = ([deg * (k + 1) / 12 for k in range(12)] + [deg] * 60
              + [deg * (1 - (k + 1) / 12) for k in range(12)] + [0.0] * 40)
    fell = lag = None
    worst = peak = 0.0
    for n, d in enumerate(frames):
        cmd = ctl.update(compute_joint_targets(body(d), None, leg_travel_limit=1.0), DT)
        for j, v in cmd.items():
            try:
                sim.set_joint_position(j, v)
            except ValueError:
                pass
        for _ in range(25):
            mujoco.mj_step(sim.model, sim.data)
        att = read_attitude(sim.model, sim.data)
        roll = abs(math.degrees(att.roll_rad))
        worst = max(worst, roll)
        clear = float(sim.data.geom_xpos[gid][2]) - z0
        peak = max(peak, clear)
        if lag is None and clear > 0.01:
            lag = (n + 1) * DT
        if fell is None and (roll > 30 or abs(math.degrees(att.pitch_rad)) > 30
                             or float(sim.data.subtree_com[0][2]) < h0 * 0.75):
            fell = n * DT
    return fell, worst, peak, lag, ctl.phase


@pytest.fixture(scope="module")
def both_lifts():
    return {"L": _physics_lift("r"), "R": _physics_lift("l")}


@pytest.mark.parametrize("leg", ["L", "R"])
def test_robot_lifts_its_leg_and_stays_up(both_lifts, leg):
    fell, _roll, peak, _lag, phase = both_lifts[leg]
    assert fell is None, f"robot {leg} leg: fell at {fell:.2f}s"
    assert peak > 0.03, f"robot {leg} foot only rose {peak * 100:.1f}cm"
    assert phase is Phase.IDLE


@pytest.mark.parametrize("leg", ["L", "R"])
def test_torso_stays_upright_while_lifting(both_lifts, leg):
    """Tilting the whole robot to shift weight leaned it 10-13 deg."""
    _fell, roll, *_ = both_lifts[leg]
    assert roll < 8.0, f"robot {leg} leg: torso leaned {roll:.1f} deg"


def test_both_legs_lift_to_the_same_height(both_lifts):
    """The tilting shift made the two legs lift to different heights for
    the same person movement."""
    left, right = both_lifts["L"][2], both_lifts["R"][2]
    assert abs(left - right) < 0.01, f"L {left * 100:.1f}cm vs R {right * 100:.1f}cm"


@pytest.mark.parametrize("leg", ["L", "R"])
def test_robot_trails_the_person_by_well_under_a_second(both_lifts, leg):
    """The first version paused ~2s before lifting."""
    lag = both_lifts[leg][3]
    assert lag is not None and lag < 0.6, f"robot {leg} leg lag {lag}"
