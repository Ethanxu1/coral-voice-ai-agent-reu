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
    lift_poses,
    shift_pose,
    should_abort,
    single_joint_pose,
    stand_pose,
    to_moves,
)
from app.vision.leg_lift_controller import ANKLE_SHIFT, HIP_RATIO  # noqa: E402

MAIN_SERVER = os.environ.get("CORAL_SERVER", "http://localhost:8000")
SLOW_MOVE_MS = 1500
SHIFT_MOVE_MS = 2000
DIRECTION_FILE = "backend/app/robot/hardware_angle_utils.py"

# What each move does in the sim (measured there), so it can be compared.
# Robot's left/right = the robot's own, as if you were standing inside it.
EXPECT_ANKLE = ("that foot tilts sideways a little (~7 deg): the edge of its sole on the "
                "ROBOT'S RIGHT side goes UP -- for the left foot that is its inner edge, "
                "for the right foot its outer edge")
EXPECT_HIP = ("that whole leg swings sideways, the foot moving about 3cm toward the "
              "ROBOT'S LEFT")
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
        self.http = httpx.Client(timeout=5.0)

    def move(self, pose: dict[str, float], duration_ms: int) -> None:
        moves = to_moves(pose, duration_ms)
        if self.dry:
            return
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
            if not values or len(values) < 3:
                return None
            return math.degrees(math.atan2(values[0], values[1]))
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


def check_directions(robot: Robot, joints: tuple[str, ...], delta: float, expect: str) -> bool:
    ok = True
    for joint in joints:
        ready(f"{joint}: robot HELD IN THE AIR, feet free", robot.unattended)
        robot.move(single_joint_pose(joint, delta), SLOW_MOVE_MS)
        robot.wait(SLOW_MOVE_MS / 1000 + 1.0)
        print(f"  Expected: {expect}.")
        good = ask("Did it move that way?", robot.unattended)
        robot.stand()
        if not good:
            ok = False
            print(f"  -> {joint}'s direction is probably the wrong sign. Flip HW_DIRECTION"
                  f"['{joint}'] in {DIRECTION_FILE}, restart the server, run this step again.")
    return ok


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


def step_lift(robot: Robot, legs: str, height: float, slow: float) -> bool:
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
        tick = DT * slow

        def stop() -> bool:
            nonlocal worst, aborted
            roll = robot.roll_deg()
            if roll is not None:
                worst = max(worst, abs(roll - base))
            if should_abort(roll, base) and not aborted:
                aborted = True
                print(f"  !! lean {'unknown' if roll is None else f'{roll - base:+.1f} deg'}"
                      " -- bringing the foot down")
            return aborted

        for pose in lift_poses(swing, height, stop=stop):
            t0 = time.monotonic()
            robot.move(pose, max(100, int(tick * 1000)))
            robot.wait(max(0.0, tick - (time.monotonic() - t0)))
        robot.stand()
        print(f"  Worst lean during the lift: {worst:.1f} deg (sim: about 2-3 deg)"
              + ("  -- ABORTED" if aborted else ""))
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
    p.add_argument("--dry-run", action="store_true", help="print the plan, move nothing")
    p.add_argument("--rehearse", action="store_true",
                   help="run on a simulator inside this script; never touches the robot")
    args = p.parse_args()
    if not 0.0 < args.height <= 0.8 or args.slow < 1.0:
        p.error("--height must be in (0, 0.8] and --slow >= 1")

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
            ok = check_directions(robot, ("l_ank_roll", "r_ank_roll"), -ANKLE_SHIFT, EXPECT_ANKLE)
        elif args.step == "hips":
            ok = check_directions(robot, ("l_hip_roll", "r_hip_roll"),
                                  -HIP_RATIO * ANKLE_SHIFT, EXPECT_HIP)
        elif args.step == "shift":
            ok = step_shift(robot)
        else:
            ok = step_lift(robot, args.leg, args.height, args.slow)
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
