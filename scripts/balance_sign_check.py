"""One-shot hardware sign check for the balance controller (Phase 3).

Not a background loop — this does exactly ONE correction and stops, so a
human can confirm the direction is right before BalanceLoop ever runs
continuously on real servos. See docs/balance-controller-progress.md
Phase 3, "Before turning this loop on for real."

What it does:
    1. Reads the real onboard IMU once (GET ROBOT_IP:9000/imu).
    2. Computes roll from the raw accelerometer directly (NOT the
       ComplementaryFilter — that's stateful and needs several ticks to
       warm up; its first call would read close to 0 regardless of the
       actual tilt, which is wrong for a single static reading. The
       confirmed formula, atan2(ax, ay) — corrected 2026-09-17, see
       complementary_filter.py's docstring for the full story — is fine
       on its own as long as the robot is held still while read, which is
       what this test requires anyway.)
    3. Runs that through the real BalanceController (same code sim uses),
       roll channels only.
    4. Converts the resulting offset to absolute servo positions and
       sends it as ONE /move call through the main server (localhost:8000,
       the same endpoint everything else in this project uses) — not
       directly to the Pi, so this goes through the usual collision
       checking and sim/hardware dispatch path.

Usage:
    Have someone hold the robot tilted (it should already be standing —
    roslaunch ainex_demo ainex_demo.launch — before this is run) and, at
    that moment, run:

        uv run python scripts/balance_sign_check.py

    It prints the measured tilt, the computed correction, and what it
    sent. Watch (and feel) whether the ankle pushes back toward level or
    further into the lean. Rate-limited to a small nudge on purpose (the
    controller's own max_rate_rad_per_s, starting from a fresh reset()) —
    this is a sign check, not a full correction.
"""

from __future__ import annotations

import math
import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from app.balance.controller import (  # noqa: E402
    AttitudeReading,
    BalanceController,
    apply_balance_offset,
)
from app.robot.angle_utils import rad_to_servo_units  # noqa: E402
from app.robot.servo_config import SERVO_ID_MAP  # noqa: E402

ROBOT_IP = os.environ.get("ROBOT_IP", "192.168.8.219")
ROBOT_AGENT_PORT = int(os.environ.get("ROBOT_AGENT_PORT", "9000"))
MAIN_SERVER = "http://localhost:8000"

_ROLL_JOINTS = ("l_ank_roll", "r_ank_roll", "l_hip_roll", "r_hip_roll")
_DT = 0.02  # one nominal tick's worth, for the rate limiter


def main() -> None:
    imu_url = f"http://{ROBOT_IP}:{ROBOT_AGENT_PORT}/imu"
    print(f"Reading {imu_url} ...")
    resp = httpx.get(imu_url, timeout=5.0)
    resp.raise_for_status()
    values = resp.json()["values"]
    if values is None or len(values) < 3:
        print("IMU returned no data (board not ready?). Aborting — nothing sent.")
        return

    ax, ay, az = values[0], values[1], values[2]
    roll_rad = math.atan2(ax, ay)  # corrected 2026-09-17 -- was atan2(az, ay)
    roll_deg = math.degrees(roll_rad)
    print(f"accel = ({ax:.3f}, {ay:.3f}, {az:.3f}) g  ->  roll = {roll_deg:.2f} deg")

    attitude = AttitudeReading(pitch_rad=0.0, roll_rad=roll_rad, pitch_rate=0.0, roll_rate=0.0)
    controller = BalanceController()
    controller.reset()
    offset = controller.update(attitude, _DT)
    roll_offset = {j: offset[j] for j in _ROLL_JOINTS}
    print("Computed offset (rad):", {j: round(v, 4) for j, v in roll_offset.items()})

    baseline = {j: 0.0 for j in _ROLL_JOINTS}
    corrected = apply_balance_offset(baseline, roll_offset)

    moves = []
    for joint, rad in corrected.items():
        servo_id = SERVO_ID_MAP.get(joint)
        if servo_id is None:
            continue
        position = rad_to_servo_units(rad)
        moves.append({"servo_id": servo_id, "position": position, "duration_ms": 800})
        # Note: `position` here is the uniform sim-unit encoding /move expects
        # (see motion.py's docstring) -- the main server converts this to the
        # ACTUAL hardware pulse (via HW_DIRECTION/STAND_PULSE) internally
        # before it reaches the Pi. This printed number is not the final
        # servo pulse -- trust the robot's physical response, not this line.
        print(f"  {joint}: {rad:+.4f} rad -> servo {servo_id} @ sim-unit {position}")

    if not moves:
        print("Nothing to send (empty offset). Aborting.")
        return

    print(f"\nSending one /move to {MAIN_SERVER} ...")
    r = httpx.post(f"{MAIN_SERVER}/move", json={"moves": moves}, timeout=10.0)
    print(f"-> {r.status_code} {r.text}")
    print(
        "\nNow: did the ankle/hip lean back TOWARD level (correct), or did it "
        "lean further INTO the tilt (backwards — do not proceed if so)?"
    )


if __name__ == "__main__":
    main()
