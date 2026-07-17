"""Manually run the robot through every pose in motions.py inside the MuJoCo viewer.

Also prints, for each joint, the servo pulse we commanded vs. the pulse MuJoCo's
"stand" keyframe considers neutral for that joint. angle_utils.rad_to_servo_units /
servo_units_to_rad currently assume a single CENTER_UNITS=500 for every joint, but
servo_config.STAND_PULSE shows several joints have an asymmetric hardware neutral
(e.g. l_sho_pitch=835, r_hip_pitch=650). Any joint whose STAND_PULSE != 500 will be
converted to the wrong MuJoCo angle -- watch for those joints visibly ending up in
the wrong place (e.g. arms flung far past where "stand" holds them).

Usage:
    python tests/sim_motion_playback.py            # cycle through all motions
    python tests/sim_motion_playback.py stand dab   # only these motions
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from robot.angle_utils import servo_units_to_rad
from robot.interface import ServoCommand
from robot.motions import MOTIONS
from robot.servo_config import SERVO_ID_MAP, STAND_PULSE
from robot.sim_controller import SimController
from simulator.mujoco_sim import AiNexSimulator

HOLD_SECONDS = 2.0


def report_mismatch(pulse: dict[str, int]) -> None:
    """Flag joints where commanded pulse relies on a non-500 hardware neutral."""
    for joint, commanded_pulse in pulse.items():
        neutral = STAND_PULSE.get(joint, 500)
        if neutral != 500:
            naive_rad = servo_units_to_rad(commanded_pulse)
            print(
                f"    [check] {joint}: commanded={commanded_pulse}  "
                f"hw_neutral={neutral} (!=500)  "
                f"naive_rad(assumes neutral=500)={naive_rad:+.3f}"
            )


def main() -> None:
    requested = sys.argv[1:]
    names = requested if requested else list(MOTIONS.keys())

    unknown = [n for n in names if n not in MOTIONS]
    if unknown:
        print(f"Unknown motion(s): {unknown}. Available: {list(MOTIONS.keys())}")
        return

    sim = AiNexSimulator()
    controller = SimController(sim)
    sim.start_viewer()
    time.sleep(1.0)  # let the viewer window come up

    try:
        for name in names:
            motion = MOTIONS[name]
            print(f"\n=== Motion: {name} ({len(motion)} frame(s)) ===")
            for frame_idx, (pulse, duration_ms) in enumerate(motion):
                print(f"  frame {frame_idx}: duration={duration_ms}ms")
                report_mismatch(pulse)
                commands = [
                    ServoCommand(servo_id=SERVO_ID_MAP[joint], position=position, duration_ms=duration_ms)
                    for joint, position in pulse.items()
                    if joint in SERVO_ID_MAP
                ]
                controller.send_commands(commands)
            time.sleep(HOLD_SECONDS)
            print(f"  resetting to stand")
            controller.reset_to_stand()
            time.sleep(HOLD_SECONDS)
    finally:
        sim.stop_viewer()


if __name__ == "__main__":
    main()
