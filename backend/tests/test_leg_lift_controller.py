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
    HOLD_MISSING_SECONDS,
    IDLE_TRAVEL,
    LOWER_RATE,
    TOUCHDOWN_RATE,
    TOUCHDOWN_ZONE,
    UNSHIFT_SECONDS,
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
        out = _run(ctl, dict(STAND), 5.0)
        assert ctl.phase is Phase.IDLE
        for j in list(STAND) + list(ANKLES):
            assert out[j] == pytest.approx(_stand(j), abs=1e-6), j


class TestLanding:
    """Traced live wobble on putting the foot down: full-speed touchdown
    rocked the robot ~4.5 deg, the hips slid back while it was still
    rocking, and a 0.25s un-shift overshot into an oscillation."""

    def _lower_from_full_lift(self, ctl):
        _run(ctl, _lifted("l"), 2.0)
        frames = []
        for _ in range(int(6.0 / DT)):
            frames.append((ctl.phase, ctl.update(dict(STAND), DT)))
        return frames

    def test_foot_slows_down_just_before_touching(self):
        ctl = LegLiftController()
        frames = self._lower_from_full_lift(ctl)
        reach = _reach("l_hip_pitch")
        zone = TOUCHDOWN_ZONE * reach
        prev = None
        checked = 0
        for _phase, out in frames:
            lift = STAND["l_hip_pitch"] - out["l_hip_pitch"]
            if prev is not None and prev <= zone and lift < prev:
                assert prev - lift <= TOUCHDOWN_RATE * reach * DT + 1e-9
                checked += 1
            prev = lift
        assert checked > 0, "never observed the final approach"

    def test_hips_start_sliding_back_as_soon_as_the_foot_is_down(self):
        """No pause after touchdown. With both feet down but the hips still
        shifted this robot keeps tipping slowly (traced -2.9 -> -5.6 deg);
        a pause raised the worst noisy landing roll from 4.9 to 7.4-8.5."""
        ctl = LegLiftController()
        frames = self._lower_from_full_lift(ctl)
        first_down = next(
            i for i, (_p, o) in enumerate(frames)
            if abs(o["l_hip_pitch"] - STAND["l_hip_pitch"]) <= 1e-6
        )
        started = next(
            i for i, (_p, o) in enumerate(frames)
            if abs(o["l_ank_roll"] - _stand("l_ank_roll") + ANKLE_SHIFT) > 1e-6
            and i >= first_down
        )
        assert (started - first_down) * DT <= 3 * DT

    def test_hips_slide_back_slowly_and_eased(self):
        """Eased in and out: slow at the start and end, fastest mid-way. A
        linear slide-back starts with an abrupt change of speed."""
        ctl = LegLiftController()
        frames = self._lower_from_full_lift(ctl)
        ankle = [o["l_ank_roll"] for p, o in frames if p is Phase.UNSHIFTING]
        assert len(ankle) * DT >= UNSHIFT_SECONDS - 2 * DT
        steps = [abs(b - a) for a, b in zip(ankle, ankle[1:])]
        mid = steps[len(steps) // 2]
        assert steps[0] < 0.5 * mid
        assert steps[-1] < 0.5 * mid


class TestWeightComesBackWhileLanding:
    """Traced live falls: the real foot touched down while the command was
    still easing in, and for ~0.6s the leg kept extending against the floor
    with the hips still shifted, pushing the robot over before a separate
    slide-back started. The weight now comes back in step with the foot."""

    def test_hips_are_centred_by_the_time_the_foot_is_down(self):
        ctl = LegLiftController()
        _run(ctl, _lifted("l"), 2.0)
        full = abs(ANKLE_SHIFT)
        for _ in range(int(4.0 / DT)):
            out = ctl.update(dict(STAND), DT)
            lift = STAND["l_hip_pitch"] - out["l_hip_pitch"]
            if lift <= 1e-6:
                shift_left = abs(out["l_ank_roll"] - _stand("l_ank_roll"))
                assert shift_left < 0.15 * full, "weight still shifted at touchdown"
                return
        pytest.fail("foot never came down")

    def test_weight_stays_across_while_the_foot_is_high(self):
        """Only the last stretch before the floor moves the weight back --
        high up, the robot is still standing on one foot."""
        ctl = LegLiftController()
        _run(ctl, _lifted("l"), 2.0)
        out = ctl.update(_lifted("l", 0.6), DT)
        assert out["l_ank_roll"] - _stand("l_ank_roll") == pytest.approx(-ANKLE_SHIFT, abs=1e-6)

    def test_re_lifting_mid_landing_waits_for_the_weight(self):
        """Marching with no gap toppled the robot every time until the foot
        was stopped from rising faster than the weight shift in place."""
        ctl = LegLiftController()
        _run(ctl, _lifted("l"), 2.0)
        _run(ctl, dict(STAND), 1.0)
        reach = _reach("l_hip_pitch")
        zone = TOUCHDOWN_ZONE * reach
        for _ in range(int(1.5 / DT)):
            out = ctl.update(_lifted("l"), DT)
            shift = abs(out["l_ank_roll"] - _stand("l_ank_roll")) / ANKLE_SHIFT
            lift = STAND["l_hip_pitch"] - out["l_hip_pitch"]
            if shift < 0.9:
                assert lift <= zone + 1e-6, "foot rose high before the weight was across"
        assert ctl.phase is Phase.LIFTING
        assert STAND["l_hip_pitch"] - out["l_hip_pitch"] > 0.3


class TestUnseenLegs:
    """Reported live: "it's not lifting its leg". A knee raised toward the
    camera is dropped by the depth gate from ~75 deg (the thigh looks too
    short on screen), and raised knees often lose visibility; both used to
    read as "leg at stand", so the robot started a lift and put the foot
    straight back down."""

    def _unseen(self, side: str) -> dict[str, float]:
        d = dict(STAND)
        for j in (f"{side}_hip_pitch", f"{side}_knee", f"{side}_hip_roll"):
            del d[j]
        return d

    def test_an_unseen_leg_holds_its_last_position(self):
        ctl = LegLiftController()
        before = _run(ctl, _lifted("l"), 2.0)
        out = _run(ctl, self._unseen("l"), HOLD_MISSING_SECONDS - 0.5)
        assert ctl.phase is Phase.LIFTING
        assert out["l_hip_pitch"] == pytest.approx(before["l_hip_pitch"], abs=1e-6)

    def test_a_leg_unseen_for_too_long_is_treated_as_down(self):
        """Bounded, so legs blocked from view for good don't leave the robot
        standing on one foot indefinitely."""
        ctl = LegLiftController()
        _run(ctl, _lifted("l"), 2.0)
        out = _run(ctl, self._unseen("l"), HOLD_MISSING_SECONDS + 5.0)
        assert ctl.phase is Phase.IDLE
        assert out["l_hip_pitch"] == pytest.approx(STAND["l_hip_pitch"], abs=1e-6)

    def test_retargeting_can_report_untrusted_legs_as_unseen(self, monkeypatch):
        sys.path.insert(0, str(Path(__file__).parent / "vision"))
        from test_pose_to_robot import _build_body  # noqa: E402

        from app import config
        from app.vision.pose_to_robot import compute_joint_targets

        monkeypatch.setattr(config, "ENABLE_LEG_TRACKING", True)
        body = _build_body()
        body[25]["visibility"] = 0.3  # left knee below the knee gate
        stand_filled = compute_joint_targets(body, None)
        omitted = compute_joint_targets(body, None, omit_untrusted_legs=True)
        assert stand_filled["l_hip_pitch"] == pytest.approx(STAND["l_hip_pitch"])
        for j in STAND:
            assert j not in omitted, j


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
    """Person raises a leg over 0.6s, holds 3s, lowers over 0.6s, stands 5s.

    Returns a dict: fell (s or None), lift_roll (worst |roll| while lifting,
    deg), peak (foot clearance, m), lag (s), phase (final), and landing
    metrics relative to the robot's resting attitude: land_roll,
    land_pitch (worst |deviation| from the moment lowering starts, deg)
    and tail_swing (roll max-min over the final second, deg -- whether it
    has actually stopped moving)."""
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
    rest = read_attitude(sim.model, sim.data)
    roll0, pitch0 = math.degrees(rest.roll_rad), math.degrees(rest.pitch_rad)
    ctl = LegLiftController()
    lower_at = 12 + 60
    frames = ([deg * (k + 1) / 12 for k in range(12)] + [deg] * 60
              + [deg * (1 - (k + 1) / 12) for k in range(12)] + [0.0] * 100)
    fell = lag = None
    lift_roll = peak = land_roll = land_pitch = 0.0
    tail: list[float] = []
    for n, d in enumerate(frames):
        cmd = ctl.update(compute_joint_targets(body(d), None, leg_travel_limit=1.0), DT)
        for j, v in cmd.items():
            try:
                sim.set_joint_position(j, v)
            except ValueError:
                pass
        for k in range(25):
            mujoco.mj_step(sim.model, sim.data)
            if n >= lower_at and k % 5 == 4:
                att = read_attitude(sim.model, sim.data)
                r = math.degrees(att.roll_rad) - roll0
                land_roll = max(land_roll, abs(r))
                land_pitch = max(land_pitch, abs(math.degrees(att.pitch_rad) - pitch0))
                if n >= len(frames) - 20:
                    tail.append(r)
        att = read_attitude(sim.model, sim.data)
        roll = abs(math.degrees(att.roll_rad))
        if n < lower_at:
            lift_roll = max(lift_roll, roll)
        clear = float(sim.data.geom_xpos[gid][2]) - z0
        peak = max(peak, clear)
        if lag is None and clear > 0.01:
            lag = (n + 1) * DT
        if fell is None and (roll > 30 or abs(math.degrees(att.pitch_rad)) > 30
                             or float(sim.data.subtree_com[0][2]) < h0 * 0.75):
            fell = n * DT
    return {
        "fell": fell, "lift_roll": lift_roll, "peak": peak, "lag": lag,
        "phase": ctl.phase, "land_roll": land_roll, "land_pitch": land_pitch,
        "tail_swing": max(tail) - min(tail),
    }


@pytest.fixture(scope="module")
def both_lifts():
    return {"L": _physics_lift("r"), "R": _physics_lift("l")}


@pytest.mark.parametrize("leg", ["L", "R"])
def test_robot_lifts_its_leg_and_stays_up(both_lifts, leg):
    r = both_lifts[leg]
    assert r["fell"] is None, f"robot {leg} leg: fell at {r['fell']:.2f}s"
    assert r["peak"] > 0.03, f"robot {leg} foot only rose {r['peak'] * 100:.1f}cm"
    assert r["phase"] is Phase.IDLE


@pytest.mark.parametrize("leg", ["L", "R"])
def test_torso_stays_upright_while_lifting(both_lifts, leg):
    """Tilting the whole robot to shift weight leaned it 10-13 deg."""
    roll = both_lifts[leg]["lift_roll"]
    assert roll < 8.0, f"robot {leg} leg: torso leaned {roll:.1f} deg"


def test_both_legs_lift_to_the_same_height(both_lifts):
    """The tilting shift made the two legs lift to different heights for
    the same person movement."""
    left, right = both_lifts["L"]["peak"], both_lifts["R"]["peak"]
    assert abs(left - right) < 0.01, f"L {left * 100:.1f}cm vs R {right * 100:.1f}cm"


@pytest.mark.parametrize("leg", ["L", "R"])
def test_robot_trails_the_person_by_well_under_a_second(both_lifts, leg):
    """The first version paused ~2s before lifting."""
    lag = both_lifts[leg]["lag"]
    assert lag is not None and lag < 0.6, f"robot {leg} leg lag {lag}"


@pytest.mark.parametrize("leg", ["L", "R"])
def test_putting_the_foot_down_is_not_wobbly(both_lifts, leg):
    """Reported live: the robot wobbled as if about to fall when the foot
    was set down, and fell once. Traced cause: full-speed touchdown, the
    hips sliding back while still rocking, and a fast un-shift overshooting
    into an oscillation (pitch rocked to +4.5 deg)."""
    r = both_lifts[leg]
    # Deterministic fixture, robot-R landing roll: 1.89 with the weight moved
    # back while the foot comes down; 4.73 if the hips only slide back after
    # touchdown; 6.59 with the original full-speed touchdown. 3.0 fails both.
    assert r["land_roll"] < 3.0, f"robot {leg}: landing rolled {r['land_roll']:.1f} deg"
    # Gross-wobble guard only -- does not distinguish old from new here.
    assert r["land_pitch"] < 3.5, f"robot {leg}: landing pitched {r['land_pitch']:.1f} deg"


@pytest.mark.parametrize("leg", ["L", "R"])
def test_robot_is_still_once_it_has_landed(both_lifts, leg):
    """Not merely upright at the end -- actually settled, not swaying."""
    swing = both_lifts[leg]["tail_swing"]
    assert swing < 1.0, f"robot {leg}: still swaying {swing:.1f} deg after landing"


# ── Physics: a HIGH knee raise, with realistic camera geometry ────────────


def _realistic_body(person_side: str, deg: float, knee_vis_drop: bool):
    """As the knee comes toward the camera its on-screen position rises
    toward the hip (on-screen thigh length ~ cos(raise)), so from ~75 deg the
    depth gate drops the leg. Earlier test bodies kept the knee's image
    position fixed and gave the hips none, so that could never happen --
    which is how "it's not lifting its leg" went unnoticed."""
    sys.path.insert(0, str(Path(__file__).parent / "vision"))
    from test_pose_to_robot import _build_body  # noqa: E402

    hip_y, thigh = 0.60, 0.18
    dy, dz = 0.4 * math.cos(math.radians(deg)), -0.4 * math.sin(math.radians(deg))
    knee_y = hip_y + thigh * math.cos(math.radians(deg))
    if person_side == "r":
        b = _build_body(r_knee=(-0.1, dy, dz), r_ankle=(-0.1, dy + 0.4, dz),
                        img_r_knee=(0.45, knee_y), img_r_ankle=(0.45, knee_y + 0.14))
        knee_idx = 26
    else:
        b = _build_body(l_knee=(0.1, dy, dz), l_ankle=(0.1, dy + 0.4, dz),
                        img_l_knee=(0.55, knee_y), img_l_ankle=(0.55, knee_y + 0.14))
        knee_idx = 25
    b[23]["x"], b[23]["y"] = 0.55, hip_y
    b[24]["x"], b[24]["y"] = 0.45, hip_y
    if knee_vis_drop and deg >= 55:
        b[knee_idx]["visibility"] = 0.4
    return b


@pytest.mark.parametrize("person_side,knee_vis_drop", [
    ("r", False), ("l", False), ("r", True), ("l", True),
])
def test_high_knee_raise_toward_the_camera_lifts_and_holds(
    monkeypatch, person_side, knee_vis_drop
):
    """Raise to 90 deg and hold 2.5s: the robot's foot must go up visibly,
    STAY up for the hold, come back down, and never fall."""
    mujoco = pytest.importorskip("mujoco")
    from app import config
    from app.balance.sim_source import read_attitude
    from app.simulator.mujoco_sim import AiNexSimulator
    from app.vision.pose_to_robot import compute_joint_targets

    monkeypatch.setattr(config, "ENABLE_LEG_TRACKING", True)
    robot_foot = "l_foot1" if person_side == "r" else "r_foot1"
    sim = AiNexSimulator()
    for _ in range(1250):
        mujoco.mj_step(sim.model, sim.data)
    gid = mujoco.mj_name2id(sim.model, mujoco.mjtObj.mjOBJ_GEOM, robot_foot)
    z0 = float(sim.data.geom_xpos[gid][2])
    ctl = LegLiftController()
    hold = 50
    frames = ([90 * (k + 1) / 12 for k in range(12)] + [90] * hold
              + [90 * (1 - (k + 1) / 12) for k in range(12)] + [0.0] * 80)
    held_up = 0
    for n, d in enumerate(frames):
        desired = compute_joint_targets(
            _realistic_body(person_side, d, knee_vis_drop), None,
            leg_travel_limit=1.0, omit_untrusted_legs=True,
        )
        for j, v in ctl.update(desired, DT).items():
            try:
                sim.set_joint_position(j, v)
            except ValueError:
                pass
        for _ in range(25):
            mujoco.mj_step(sim.model, sim.data)
        att = read_attitude(sim.model, sim.data)
        assert abs(math.degrees(att.roll_rad)) < 30, f"fell at {n * DT:.2f}s"
        clear = float(sim.data.geom_xpos[gid][2]) - z0
        if 12 + 10 <= n < 12 + hold and clear > 0.03:
            held_up += 1
    assert held_up == hold - 10, f"foot up for only {held_up}/{hold - 10} hold frames"
    assert ctl.phase is Phase.IDLE
