"""Step-by-step hardware check before letting follow mode lift a real leg.

Each step moves only the leg and ankle-roll servos, slowly, through the
main server's /move (collision + fall check, sim mirror, normal hardware
conversion), then asks you whether the robot did what the sim does.

Steps, in order -- do not skip ahead:
  ankles  robot HELD IN THE AIR: each ankle roll alone, checks its direction
  hips    robot HELD IN THE AIR: each hip roll alone, checks its direction
  shift   robot STANDING, spotter ready: weight over one foot and back, no lift
  lift    robot STANDING, spotter ready: small real lift via LegLiftController

Before running:
  - start everything in hardware mode:  ./run.sh -live   (add -ip <robot_ip>
    if the robot is not at the default IP, and then also run this script
    with ROBOT_IP=<robot_ip> in front so it reads the right IMU)
  - robot powered, standing in its stand pose
  - one person holding or spotting the robot the whole time

Usage (from the repo root):
  uv run python scripts/leg_lift_hardware_check.py ankles
  uv run python scripts/leg_lift_hardware_check.py hips
  uv run python scripts/leg_lift_hardware_check.py shift
  uv run python scripts/leg_lift_hardware_check.py lift --height 0.2 --slow 3
  add --dry-run to any step to print what it would do without moving anything
  add --rehearse to run it on a simulator inside this script (opens a viewer;
    never touches the server or the robot; the sim's tilt stands in for the IMU)

Ctrl-C at any time sends the legs back to stand.
"""

from __future__ import annotations

import argparse
import itertools
import math
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.config import ROBOT_AGENT_PORT, ROBOT_IP  # noqa: E402
from app.robot.leg_lift_check import (  # noqa: E402
    ABORT_ROLL_DEG,
    DT,
    LeanGuard,
    foot_fraction,
    lean_breakdown,
    lift_poses,
    shift_fraction,
    shift_pose,
    single_joint_pose,
    stand_pose,
    to_moves,
    with_stance_comp,
)
from app.robot.hardware_angle_utils import hardware_units_to_rad, rad_to_hardware_units  # noqa: E402
from app.robot.servo_config import SERVO_ID_MAP  # noqa: E402
from app.vision.leg_lift_controller import ANKLE_SHIFT, HIP_RATIO  # noqa: E402

MAIN_SERVER = os.environ.get("CORAL_SERVER", "http://localhost:8000")
SLOW_MOVE_MS = 1500
SHIFT_MOVE_MS = 2000
# Wall time each lift command covers (see step_lift).
SEGMENT_S = 0.6
DIRECTION_FILE = "backend/app/robot/hardware_angle_utils.py"

# What each move does in the sim (measured there), so it can be compared.
# Robot's left/right = the robot's own, as if you were standing inside it.
# Both ankles tilt the same way in space, and both legs swing the same way --
# so for one leg that is "inner/inward" and for the other "outer/outward".
EXPECT_DIRECTION = {
    "l_ank_roll": "the LEFT foot tilts a little (~7 deg) so its INNER edge (the side "
                  "facing the other foot) LIFTS and its outer edge goes down",
    "r_ank_roll": "the RIGHT foot tilts a little (~7 deg) so its OUTER edge (the side "
                  "away from the other foot) LIFTS and its inner edge goes down",
    "l_hip_roll": "the LEFT leg swings OUTWARD, the foot moving about 3cm AWAY from the "
                  "other leg",
    "r_hip_roll": "the RIGHT leg swings OUTWARD, the foot moving about 3cm AWAY from the "
                  "other leg",
}
EXPECT_SHIFT = {
    "l": "the hips slide about 3cm over the ROBOT'S RIGHT foot; both feet stay flat "
         "on the floor; the torso stays upright",
    "r": "the hips slide about 3cm over the ROBOT'S LEFT foot; both feet stay flat "
         "on the floor; the torso stays upright",
}


class Robot:
    def __init__(self, dry_run: bool):
        self.dry = dry_run
        self.rehearse = False
        self.last_raw: list[float] | None = None  # raw IMU of the last roll_deg() call
        self.http = httpx.Client(timeout=5.0)

    def move(self, pose: dict[str, float], duration_ms: int) -> None:
        moves = to_moves(pose, duration_ms)
        if self.dry:
            return
        r = self.http.post(f"{MAIN_SERVER}/move", json={"moves": moves})
        if r.status_code == 503:
            # The robot's Pi refuses a move while another is still executing
            # ("robot busy"); the app reports that as 503. Seen once,
            # 2026-10-02, on the first lift command. One retry after a pause.
            print("  (robot busy -- retrying that move once)")
            time.sleep(0.4)
            r = self.http.post(f"{MAIN_SERVER}/move", json={"moves": moves})
        r.raise_for_status()
        body = r.json()
        if body.get("status") == "blocked":
            raise RuntimeError(f"server's fall check BLOCKED this move: {body.get('safety')}")

    def roll_deg(self) -> float | None:
        """Torso roll from the onboard IMU (same formula as balance_sign_check)."""
        if self.dry:
            return 0.0
        try:
            r = self.http.get(f"http://{ROBOT_IP}:{ROBOT_AGENT_PORT}/imu", timeout=1.0)
            values = r.json().get("values")
            self.last_raw = values
            if not values or len(values) < 3:
                return None
            return math.degrees(math.atan2(values[0], values[1]))
        except Exception:
            return None

    def positions(self) -> dict[int, int] | None:
        """The servos' ACTUAL positions {servo_id: pulse}, or None if the
        robot can't report them (older Pi code, or a failed read)."""
        if self.dry:
            return None
        try:
            r = self.http.get(f"http://{ROBOT_IP}:{ROBOT_AGENT_PORT}/positions", timeout=1.0)
            if r.status_code != 200:
                return None
            return {int(k): int(v) for k, v in r.json()["positions"].items()}
        except Exception:
            return None

    def stand(self) -> None:
        self.move(stand_pose(), SLOW_MOVE_MS)
        self.wait(SLOW_MOVE_MS / 1000 + 0.3)

    def wait(self, seconds: float) -> None:
        if not self.dry:
            time.sleep(seconds)

    @property
    def unattended(self) -> bool:
        return self.dry or self.rehearse


class SimRobot(Robot):
    """Rehearsal: its own simulator, never the server or the real robot."""

    def __init__(self, open_window: bool = True):
        super().__init__(dry_run=False)
        from app.robot.interface import ServoCommand
        from app.robot.sim_controller import SimController
        from app.simulator.mujoco_sim import AiNexSimulator

        self.rehearse = True
        self._cmd = ServoCommand
        self.sim = AiNexSimulator()
        self.sim.start_viewer(open_window=open_window)
        time.sleep(2.5)  # let it settle on its feet
        self.ctrl = SimController(self.sim)

    def move(self, pose: dict[str, float], duration_ms: int) -> None:
        self.ctrl.send_commands([self._cmd(**m) for m in to_moves(pose, duration_ms)])

    def positions(self) -> dict[int, int] | None:
        import mujoco

        m, d = self.sim.model, self.sim.data
        out = {}
        with self.sim._lock:
            for joint, sid in SERVO_ID_MAP.items():
                jid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, joint)
                if jid >= 0:
                    out[sid] = rad_to_hardware_units(float(d.qpos[m.jnt_qposadr[jid]]), joint)
        return out

    def roll_deg(self) -> float | None:
        from app.balance.sim_source import read_attitude

        with self.sim._lock:
            return math.degrees(read_attitude(self.sim.model, self.sim.data).roll_rad)


def ask(question: str, dry: bool) -> bool:
    if dry:
        print(f"  [no questions] {question} -> assuming yes")
        return True
    while True:
        a = input(f"  {question} [y/n] ").strip().lower()
        if a in ("y", "n"):
            return a == "y"


def ready(what: str, dry: bool) -> None:
    print(f"\n>>> {what}")
    if not dry:
        input("    Press Enter when ready (Ctrl-C to stop) ...")


# Each hip is tested swinging OUTWARD. Inward, the feet are ~1cm apart, so the
# server's collision check cut the right hip's inward test to 15% (2026-10-02):
# it barely moved and looked wrong. The shift moves both legs together, so it
# never closes that gap.
HIP_TEST = {"l_hip_roll": -HIP_RATIO * ANKLE_SHIFT, "r_hip_roll": +HIP_RATIO * ANKLE_SHIFT}


def check_directions(robot: Robot, deltas: dict[str, float]) -> bool:
    ok = True
    for joint, delta in deltas.items():
        ready(f"{joint}: robot HELD IN THE AIR, feet free", robot.unattended)
        robot.move(single_joint_pose(joint, delta), SLOW_MOVE_MS)
        robot.wait(SLOW_MOVE_MS / 1000 + 1.0)
        print(f"  Expected: {EXPECT_DIRECTION[joint]}.")
        good = ask("Did it move that way?", robot.unattended)
        robot.stand()
        if not good:
            ok = False
            print("  -> Did it move the OPPOSITE way, or not at all? Tell Claude which.")
            print(f"     If clearly the opposite way, {joint}'s direction is probably the wrong sign. Flip HW_DIRECTION"
                  f"['{joint}'] in {DIRECTION_FILE}, restart the server, run this step again.")
            break
    return ok


# Ankle tilt is only ~3mm at the sole's edge -- too small to judge from
# stand. So each ankle rocks between -A and +A (a 14 deg swing, easy to see)
# and stops at -A; the question is which edge is higher THERE. Larger
# angles are blocked by the server's fall check for the right ankle.
EXPECT_HIGHER_EDGE = {"l_ank_roll": "inner", "r_ank_roll": "outer"}
ROCK_MOVE_MS = 700


def check_ankles(robot: Robot) -> bool:
    for joint in ("l_ank_roll", "r_ank_roll"):
        foot = "LEFT" if joint.startswith("l") else "RIGHT"
        ready(f"{foot} ankle: robot HELD IN THE AIR, feet free. Watch the {foot} foot: it will "
              "rock side to side 3 times, then stop tilted", robot.unattended)
        for delta in (-ANKLE_SHIFT, ANKLE_SHIFT) * 3 + (-ANKLE_SHIFT,):
            robot.move(single_joint_pose(joint, delta), ROCK_MOVE_MS)
            robot.wait(ROCK_MOVE_MS / 1000 + 0.3)
        robot.wait(0.5)
        print(f"  It is stopped now. Look at the {foot} foot's sole: the INNER edge faces the "
              "other foot, the OUTER edge faces away.")
        if robot.unattended:
            seen = EXPECT_HIGHER_EDGE[joint]
            print(f"  [no questions] which edge is higher? -> assuming {seen}")
        else:
            seen = ""
            while seen not in ("inner", "outer", "same"):
                seen = input("  Which edge is HIGHER right now? [inner/outer/same] ").strip().lower()
        robot.stand()
        if seen == "same":
            print(f"  -> {joint} did not visibly move. Tell Claude -- that is not a direction problem.")
            return False
        if seen != EXPECT_HIGHER_EDGE[joint]:
            print(f"  -> {joint} turns the OPPOSITE way to the sim. Its HW_DIRECTION sign in "
                  f"{DIRECTION_FILE} is probably wrong. Tell Claude before changing anything.")
            return False
        print(f"  -> {joint} matches the sim.")
    return True


def step_shift(robot: Robot) -> bool:
    ok = True
    for swing in ("l", "r"):
        ready(f"Shift for lifting the ROBOT'S {'LEFT' if swing == 'l' else 'RIGHT'} leg "
              "(no lift): robot STANDING, spotter ready", robot.unattended)
        base = robot.roll_deg()
        robot.move(shift_pose(swing), SHIFT_MOVE_MS)
        robot.wait(SHIFT_MOVE_MS / 1000 + 1.5)
        roll = robot.roll_deg()
        robot.stand()
        print(f"  Expected: {EXPECT_SHIFT[swing]}.")
        if base is not None and roll is not None:
            print(f"  IMU roll: {base:+.1f} -> {roll:+.1f} deg (change {roll - base:+.1f}; "
                  f"sim: 1-3 deg)")
            if abs(roll - base) > ABORT_ROLL_DEG:
                print("  -> leaned far more than the sim. Do NOT run the lift step.")
                ok = False
        else:
            print("  (no IMU reading -- judge by eye)")
        ok = ask("Did it do that, without a foot lifting or the robot tipping?", robot.unattended) and ok
    return ok


STANCE_JOINTS = ("ank_roll", "hip_roll")


def stance_drift(actual: dict[int, int] | None, sent: dict[str, float], swing: str) -> list:
    """Standing ankle and hip roll: commanded and actual angle (deg), and
    actual minus commanded. Step 3 needs to know if/how the standing ankle
    gives on one foot. None where the robot can't report positions."""
    stance = "r" if swing == "l" else "l"
    out = []
    for j in STANCE_JOINTS:
        joint = f"{stance}_{j}"
        cmd = math.degrees(sent[joint])
        sid = SERVO_ID_MAP[joint]
        if actual is None or sid not in actual:
            out += [round(cmd, 2), None, None]
            continue
        act = math.degrees(hardware_units_to_rad(actual[sid], joint))
        out += [round(cmd, 2), round(act, 2), round(act - cmd, 2)]
    return out


def report_drift(rows: list[tuple]) -> None:
    """How far the standing ankle/hip sat from where they were told to be,
    before the foot lifted vs with it up."""
    for k, j in enumerate(STANCE_JOINTS):
        col = 10 + 3 * k + 2
        down = [r[col] for r in rows if r[col] is not None and r[2] >= 0.98 and r[3] < 0.02]
        up = [r[col] for r in rows if r[col] is not None and r[3] >= 0.1]
        if not down and not up:
            print(f"  Standing {j.replace('_', ' ')}: robot did not report positions")
            continue
        avg = lambda xs: "n/a" if not xs else f"{sum(xs) / len(xs):+.1f}"  # noqa: E731
        worst = "n/a" if not up else f"{max(up, key=abs):+.1f}"
        print(f"  Standing {j.replace('_', ' ')}, actual minus commanded (deg): "
              f"hips slid, foot down {avg(down)} | foot up {avg(up)} (worst {worst})")


def report_lean(rows: list[tuple], swing: str) -> None:
    """Print when the lean happened and save every tick for Claude to read."""
    fmt = lambda v: "n/a" if v is None else f"{v:+.1f} deg"  # noqa: E731
    b = lean_breakdown(rows)
    print(f"  Lean once the hips finished sliding (foot still down): {fmt(b['after_shift'])}")
    print(f"  Lean as the foot left the floor:                        {fmt(b['foot_leaves'])}")
    print(f"  Worst lean with the foot up:                            {fmt(b['worst_foot_up'])}")
    if b["worst"] is not None:
        print(f"  Worst lean overall {fmt(b['worst'])}, at hips {b['worst_shift']:.0%} slid, "
              f"foot {b['worst_foot']:.0%} up")
    out_dir = os.path.join(os.path.dirname(__file__), "..", "logs", "leg_lift_check")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{time.strftime('%Y%m%d_%H%M%S')}_lift_{swing}.csv")
    with open(path, "w") as f:
        f.write("t_s,lean_deg,hips_slid,foot_up,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,"
                "stance_ank_cmd_deg,stance_ank_act_deg,stance_ank_drift_deg,"
                "stance_hip_cmd_deg,stance_hip_act_deg,stance_hip_drift_deg\n")
        for r in rows:
            f.write(",".join("" if v is None else str(v) for v in r) + "\n")
    print(f"  Every tick saved to {os.path.relpath(path)}")


def step_lift(robot: Robot, legs: str, height: float, slow: float, stance_comp_deg: float = 0.0) -> bool:
    ok = True
    for swing in (("l", "r") if legs == "both" else (legs,)):
        ready(f"LIFT the ROBOT'S {'LEFT' if swing == 'l' else 'RIGHT'} leg to {height:.0%} "
              f"of its travel, {slow:g}x slower than the sim: robot STANDING, spotter's "
              f"hands ready to catch", robot.unattended)
        base = robot.roll_deg()
        if base is None:
            print("  No IMU reading -- the lift needs it to stop itself. Aborting.")
            return False
        worst, aborted = 0.0, False
        guard = LeanGuard(base)
        # The robot's /move blocks until the motion ends, ~0.3-0.5 s per call.
        # Short moves therefore came out as move-stop-move jolts (2026-10-02),
        # which the IMU read as lean. So each command covers SEGMENT_S of
        # motion: the controller is stepped SEGMENT_S / slow ahead and the
        # servos glide to that pose over the whole segment.
        per_segment = max(1, round(SEGMENT_S / (DT * slow)))
        poses = lift_poses(swing, height, stop=lambda: aborted)
        rows: list[tuple] = []
        start = time.monotonic()
        while True:
            chunk = list(itertools.islice(poses, per_segment))
            if not chunk:
                break
            pose = chunk[-1]
            sent = with_stance_comp(pose, swing, math.radians(stance_comp_deg))
            robot.move(sent, int(SEGMENT_S * 1000))
            roll = robot.roll_deg()
            lean = None if roll is None else roll - base
            if lean is not None:
                worst = max(worst, abs(lean))
            raw = [round(v, 4) for v in (robot.last_raw or [])[:6]]
            rows.append((round(time.monotonic() - start, 3),
                         None if lean is None else round(lean, 2),
                         round(shift_fraction(pose, swing), 3), round(foot_fraction(pose, swing), 3),
                         *(raw + [None] * (6 - len(raw))),
                         *stance_drift(robot.positions(), sent, swing)))
            if not aborted and guard.update(roll):
                aborted = True
                print(f"  !! lean {'unknown' if lean is None else f'{lean:+.1f} deg'} held "
                      "-- bringing the foot down")
        robot.stand()
        print(f"  Worst lean during the lift: {worst:.1f} deg (sim: about 2-3 deg)"
              + ("  -- ABORTED" if aborted else ""))
        report_lean(rows, swing)
        report_drift(rows)
        ok = ask("Did it lift the foot cleanly, stay upright, and set it down "
                 "without tipping?", robot.unattended) and ok and not aborted
    return ok


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=("ankles", "hips", "shift", "lift"))
    p.add_argument("--leg", choices=("l", "r", "both"), default="both",
                   help="lift step: which robot leg")
    p.add_argument("--height", type=float, default=0.2,
                   help="lift step: raise as a fraction of hip travel (default 0.2, sim tested up to 0.8)")
    p.add_argument("--slow", type=float, default=3.0,
                   help="lift step: how many times slower than the sim (default 3)")
    p.add_argument("--shift-scale", type=float, default=1.0,
                   help="shift/lift: multiply the hip slide (ANKLE_SHIFT) for this run only, "
                        "e.g. 1.25. Experiment knob -- does not change the controller file")
    p.add_argument("--stance-comp", type=float, default=0.0,
                   help="lift: degrees to ease the STANDING hip roll back while the foot is up (0-12). "
                        "EXPERIMENTAL: on 2026-10-02 4 deg (left) and 8 deg (right) both nearly "
                        "tipped the robot -- see docs/cbf-whole-body-progress.md Phase 2.17")
    p.add_argument("--dry-run", action="store_true", help="print the plan, move nothing")
    p.add_argument("--rehearse", action="store_true",
                   help="run on a simulator inside this script; never touches the robot")
    args = p.parse_args()
    if not 0.0 < args.height <= 0.8 or args.slow < 1.0:
        p.error("--height must be in (0, 0.8] and --slow >= 1")
    if not 0.0 <= args.stance_comp <= 12.0:
        p.error("--stance-comp must be between 0 and 12 degrees")
    if not 0.5 <= args.shift_scale <= 1.6:
        p.error("--shift-scale must be between 0.5 and 1.6")
    if args.shift_scale != 1.0:
        import app.vision.leg_lift_controller as llc
        llc.ANKLE_SHIFT *= args.shift_scale
        print(f"Hip slide scaled x{args.shift_scale:g} for this run "
              f"(ANKLE_SHIFT {llc.ANKLE_SHIFT:.3f} rad)")

    robot = (SimRobot(open_window=not os.environ.get("CORAL_HEADLESS"))
             if args.rehearse else Robot(args.dry_run))
    quiet = args.dry_run or args.rehearse
    print(f"Server {MAIN_SERVER}, IMU at {ROBOT_IP}:{ROBOT_AGENT_PORT}"
          + ("  [DRY RUN -- nothing will move]" if args.dry_run else "")
          + ("  [REHEARSAL -- own simulator, robot untouched]" if args.rehearse else ""))
    try:
        ready("First: legs to stand", quiet)
        robot.stand()
        if args.step == "ankles":
            ok = check_ankles(robot)
        elif args.step == "hips":
            ok = check_directions(robot, HIP_TEST)
        elif args.step == "shift":
            ok = step_shift(robot)
        else:
            ok = step_lift(robot, args.leg, args.height, args.slow, args.stance_comp)
    except KeyboardInterrupt:
        print("\nStopped -- legs back to stand.")
        robot.stand()
        return
    except Exception as e:
        print(f"\nError: {e}\nLegs back to stand.")
        try:
            robot.stand()
        except Exception as e2:
            print(f"Could not send stand either ({e2}) -- hold the robot and stop the server.")
        sys.exit(1)
    print("\nRESULT:", "PASSED -- go on to the next step." if ok else
          "NOT PASSED -- fix what is listed above before the next step.")


if __name__ == "__main__":
    main()
