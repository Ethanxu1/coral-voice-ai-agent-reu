"""Measure the real pulse-per-degree response of each arm servo on the physical
robot, so hardware_angle_utils's single global TICKS_PER_RAD (one slope for every
joint) can be replaced with a per-joint fit.

Why this is manual: the pi's /feedback and /positions endpoints are stubs that
just echo STAND_PULSE (see robot_server.py) — there is no electronic position
readback. So for each pulse we command, a human reads the real angle off the
limb with a protractor/goniometer and types it in.

Scope: only the 8 arm joints compute_joint_targets ever emits are swept
(l/r_sho_pitch, l/r_sho_roll, l/r_el_pitch, l/r_el_yaw). Head servos (23/24) are
not physically present on this robot (see servo_config.py), and legs are
excluded — compute_joint_targets never targets them, and sweeping hip/knee
pulses on a standing robot risks tipping it over.

Measurement convention: for each joint, pick one physical reference direction
and always measure "how far past stand, in degrees, in that direction" — sign
however you like, just be consistent within a joint's sweep. The script fits
pulse = slope * angle + intercept from your numbers; reconciling that sign with
compute_joint_targets's convention (and updating hardware_angle_utils) is a
manual step afterward, printed at the end.

Usage:
    ROBOT_IP=192.168.8.219 python tests/calibrate_hardware_angles.py
    python tests/calibrate_hardware_angles.py --joints l_sho_pitch r_sho_pitch
    python tests/calibrate_hardware_angles.py --points 7 --span 250
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from robot.hardware_angle_utils import HW_SERVO_LIMITS
from robot.servo_config import SERVO_ID_MAP, STAND_PULSE

ROBOT_IP = os.getenv("ROBOT_IP", "192.168.8.219")
ROBOT_AGENT_PORT = int(os.getenv("ROBOT_AGENT_PORT", "9000"))
BASE = f"http://{ROBOT_IP}:{ROBOT_AGENT_PORT}"

# The only joints compute_joint_targets ever produces. Head servos (23/24) don't
# physically exist on this robot; legs are excluded for stability.
DEFAULT_JOINTS = [
    "l_sho_pitch", "r_sho_pitch",
    "l_sho_roll",  "r_sho_roll",
    "l_el_pitch",  "r_el_pitch",
    "l_el_yaw",    "r_el_yaw",
]

# Script-level safety rail, independent of /move's own clamping — this is a
# first calibration pass, so stay well clear of the mechanical end-stops unless
# a tighter HW_SERVO_LIMITS entry (e.g. the damaged r_el_yaw) says otherwise.
SAFE_LO, SAFE_HI = 50, 950

client = httpx.Client(timeout=5.0)


def _post_move(payload: list[dict]) -> None:
    client.post(f"{BASE}/move", json=payload)


def reset_to_stand(duration_ms: int = 800) -> None:
    payload = [
        {"servo_id": sid, "position": STAND_PULSE[name], "duration_ms": duration_ms}
        for name, sid in SERVO_ID_MAP.items()
        if name in STAND_PULSE
    ]
    _post_move(payload)


def move_single(joint: str, pulse: int, duration_ms: int) -> None:
    servo_id = SERVO_ID_MAP[joint]
    _post_move([{"servo_id": servo_id, "position": pulse, "duration_ms": duration_ms}])


def joint_range(joint: str, span: int) -> tuple[int, int]:
    stand = STAND_PULSE[joint]
    lo, hi = stand - span, stand + span
    hw_lo, hw_hi = HW_SERVO_LIMITS.get(joint, (SAFE_LO, SAFE_HI))
    return max(lo, hw_lo, SAFE_LO), min(hi, hw_hi, SAFE_HI)


def sweep_joint(
    joint: str, points: int, span: int, duration_ms: int, settle_s: float,
) -> list[tuple[int, float]]:
    lo, hi = joint_range(joint, span)
    if lo >= hi:
        print(f"  [skip] {joint}: safe range collapsed to nothing ({lo}..{hi})")
        return []
    pulses = [round(lo + i * (hi - lo) / (points - 1)) for i in range(points)]

    print(f"\n=== {joint} — sweeping pulses {pulses} (stand={STAND_PULSE[joint]}) ===")
    reset_to_stand()
    time.sleep(1.0)

    samples: list[tuple[int, float]] = []
    for pulse in pulses:
        move_single(joint, pulse, duration_ms)
        time.sleep(settle_s)
        raw = input(f"  pulse {pulse}: measured angle (deg, blank to skip)? ").strip()
        if not raw:
            continue
        try:
            samples.append((pulse, float(raw)))
        except ValueError:
            print("  (not a number, skipping this point)")

    reset_to_stand()
    time.sleep(1.0)
    return samples


def fit_slope(samples: list[tuple[int, float]]) -> dict:
    if len(samples) < 2:
        return {"n": len(samples), "slope_units_per_deg": None, "intercept_pulse": None, "r_squared": None}

    pulses = np.array([p for p, _ in samples], dtype=float)
    angles = np.array([a for _, a in samples], dtype=float)

    # Fit pulse = slope * angle + intercept — this is the direction
    # rad_to_hardware_units needs (angle -> pulse), not the reverse.
    slope, intercept = np.polyfit(angles, pulses, 1)
    predicted = slope * angles + intercept
    ss_res = float(np.sum((pulses - predicted) ** 2))
    ss_tot = float(np.sum((pulses - pulses.mean()) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 1e-9 else 1.0

    return {
        "n": len(samples),
        "slope_units_per_deg": round(float(slope), 4),
        "slope_units_per_rad": round(float(slope) * 180.0 / np.pi, 3),
        "intercept_pulse": round(float(intercept), 2),
        "r_squared": round(r_squared, 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--joints", nargs="+", default=DEFAULT_JOINTS, choices=DEFAULT_JOINTS)
    parser.add_argument("--points", type=int, default=5, help="pulses sampled per joint")
    parser.add_argument("--span", type=int, default=150, help="+/- pulse units around stand to sweep")
    parser.add_argument("--duration-ms", type=int, default=600, help="move time per commanded step")
    parser.add_argument("--settle-s", type=float, default=1.5, help="pause before prompting for a measurement")
    parser.add_argument("--output", default="hardware_calibration.json")
    args = parser.parse_args()

    print(f"Robot agent: {BASE}")
    print(f"Joints to calibrate: {args.joints}")
    print("Returning to stand before starting...")
    reset_to_stand()
    time.sleep(1.5)

    results: dict[str, dict] = {}
    try:
        for joint in args.joints:
            samples = sweep_joint(joint, args.points, args.span, args.duration_ms, args.settle_s)
            fit = fit_slope(samples)
            fit["samples"] = samples
            fit["current_stand_pulse"] = STAND_PULSE[joint]
            results[joint] = fit
            if fit["slope_units_per_deg"] is not None:
                print(f"  fit: {fit['slope_units_per_deg']} units/deg  "
                      f"({fit['slope_units_per_rad']} units/rad)  r²={fit['r_squared']}")
            else:
                print(f"  not enough points to fit ({fit['n']} collected)")
    except KeyboardInterrupt:
        print("\nInterrupted — returning to stand.")
    finally:
        reset_to_stand()

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {args.output}")

    print(
        "\nNext step (manual): reconcile each joint's measured sign/slope with "
        "compute_joint_targets's angle convention, then update HW_DIRECTION and "
        "replace the shared TICKS_PER_RAD in hardware_angle_utils.py with these "
        "per-joint slope_units_per_rad values."
    )


if __name__ == "__main__":
    main()
