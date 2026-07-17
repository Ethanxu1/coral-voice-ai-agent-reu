"""Standalone test harness for the CollisionChecker.

Runs the checker across a fixed sequence of poses and reports, for each leg,
whether the interpolated joint-space path stays self-collision-free — and if
not, how far along it can safely travel and which geom pairs would touch.

The checker rolls the motion out step-by-step (mj_forward at each interpolation
step), so it catches *en-route* collisions mid-motion, not just at the
endpoints. This harness exercises that: stand -> pose 1 -> pose 2.

No server, no hardware — just the kinematic checker, plus (by default) a
native MuJoCo viewer window so you can see each leg's clamped result live
instead of only reading the JSON.

Usage:
    uv run collision-test                     # run, show the viewer, print a report
    uv run collision-test out.json            # also save the JSON report there
    CORAL_NO_VIEWER=1 uv run collision-test   # headless (e.g. CI)
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import mujoco
import mujoco.viewer
from loguru import logger

from coral_agent.collision.collision_checker import CollisionChecker

# How long to hold each leg's resulting pose on screen before moving to the next.
_LEG_PAUSE_S = 1.5


def _reexec_under_mjpython_if_needed() -> None:
    """Re-exec under `mjpython` on macOS so the MuJoCo viewer window can open.

    Mirrors server.py's helper of the same name: MuJoCo's interactive viewer
    (`launch_passive`) raises on macOS unless launched via `mjpython`, which
    keeps the Cocoa UI loop on the real main thread. No-op off macOS, once
    already re-exec'd, or when CORAL_NO_VIEWER=1.
    """
    if sys.platform != "darwin":
        return
    if os.environ.get("CORAL_MJPYTHON") == "1" or os.environ.get("CORAL_NO_VIEWER") == "1":
        return
    mjpython = Path(sys.executable).with_name("mjpython")
    if not mjpython.exists():
        logger.warning(
            "mjpython not found next to the interpreter; the MuJoCo viewer window "
            "won't open on macOS. Set CORAL_NO_VIEWER=1 to silence this."
        )
        return
    argv = sys.argv if sys.argv and Path(sys.argv[0]).exists() else ["-m", "coral_agent.collision.collision_test"]
    os.environ["CORAL_MJPYTHON"] = "1"
    logger.info("macOS: re-launching under mjpython so the MuJoCo viewer window opens...")
    os.execv(str(mjpython), [str(mjpython), *argv])

# Poses are joint targets in radians. Legs are the stand stance; the arms differ.
POSE_1: dict[str, float] = {
    "head_pan": 0.00, "head_tilt": 0.00,
    "l_sho_pitch": 0.76, "l_sho_roll": -1.36, "l_el_pitch": -1.40, "l_el_yaw": -1.57, "l_gripper": 0.00,
    "r_sho_pitch": 1.36, "r_sho_roll": 1.36, "r_el_pitch": -1.40, "r_el_yaw": 1.57, "r_gripper": 0.00,
    "l_hip_yaw": 0.00, "l_hip_roll": 0.00, "l_hip_pitch": -0.49, "l_knee": 0.93, "l_ank_pitch": 0.45, "l_ank_roll": 0.00,
    "r_hip_yaw": 0.00, "r_hip_roll": 0.00, "r_hip_pitch": 0.49, "r_knee": -0.93, "r_ank_pitch": -0.45, "r_ank_roll": -0.07,
}

POSE_2: dict[str, float] = {
    "head_pan": 0.00, "head_tilt": 0.00,
    "l_sho_pitch": 1.36, "l_sho_roll": -1.36, "l_el_pitch": -1.40, "l_el_yaw": -1.57, "l_gripper": 0.00,
    "r_sho_pitch": 0.76, "r_sho_roll": 1.36, "r_el_pitch": -1.49, "r_el_yaw": 1.57, "r_gripper": 0.00,
    "l_hip_yaw": 0.00, "l_hip_roll": 0.00, "l_hip_pitch": -0.49, "l_knee": 0.93, "l_ank_pitch": 0.45, "l_ank_roll": 0.00,
    "r_hip_yaw": 0.00, "r_hip_roll": 0.00, "r_hip_pitch": 0.49, "r_knee": -0.93, "r_ank_pitch": -0.45, "r_ank_roll": -0.07,
}


def _run_leg(
    checker: CollisionChecker,
    label: str,
    current: dict[str, float],
    target: dict[str, float],
    viewer: mujoco.viewer.Handle | None = None,
) -> dict:
    """Check one current->target transition and return a report dict.

    If `viewer` is an open handle (launched against checker.model/checker.data
    in main()), renders the safe (possibly clamped) result and syncs it so the
    outcome is visible before moving on to the next leg.
    """
    safe_joints, safe_fraction, bad_pairs = checker.check_trajectory(current, target)
    collided = safe_fraction < 1.0

    # Joints the checker had to pull back from their commanded target.
    clamped = {
        j: {"target": round(target[j], 4), "safe": round(safe_joints[j], 4)}
        for j in target
        if j in safe_joints and abs(safe_joints[j] - target[j]) > 1e-6
    }

    status = "COLLISION" if collided else "clear"
    logger.info(
        f"{label}: {status} — safe_fraction={safe_fraction:.0%}"
        + (f", pairs={bad_pairs}" if bad_pairs else "")
    )
    for j, v in clamped.items():
        logger.info(f"    {j}: target {v['target']} -> clamped to {v['safe']}")

    if viewer is not None and viewer.is_running():
        checker.render_pose(safe_joints)
        viewer.sync()
        time.sleep(_LEG_PAUSE_S)

    return {
        "label": label,
        "collided": collided,
        "safe_fraction": safe_fraction,
        "bad_pairs": bad_pairs,
        "clamped_joints": clamped,
        "current_joints": {k: round(v, 4) for k, v in current.items()},
        "target_joints": {k: round(v, 4) for k, v in target.items()},
        "safe_joints": {k: round(v, 4) for k, v in safe_joints.items()},
    }


def run_collision_test(
    checker: CollisionChecker | None = None,
    viewer: mujoco.viewer.Handle | None = None,
) -> dict:
    """Run the stand -> pose 1 -> pose 2 sequence and return the full report.

    Pass an existing `checker` to reuse its live mjData — e.g. so a viewer
    launched against checker.model/checker.data (see main()) shows each leg's
    result as it runs. Without one, builds a fresh headless CollisionChecker.
    """
    if checker is None:
        checker = CollisionChecker()
    stand = checker.stand_joints()

    legs = [
        _run_leg(checker, "stand -> pose 1", stand, POSE_1, viewer),
        _run_leg(checker, "pose 1 -> pose 2", POSE_1, POSE_2, viewer),
    ]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "num_steps": checker.num_steps,
        "buffer_steps": checker.buffer_steps,
        "any_collision": any(leg["collided"] for leg in legs),
        "legs": legs,
    }


def main() -> None:
    """Entry point: run the sequence, print a summary, and save a JSON report.

    Opens the native MuJoCo viewer by default so you can watch each leg's
    clamped pose live (holds it open after the run until you close the
    window). On macOS this needs `mjpython`, so the process re-execs under it
    automatically, same as server.py. Set CORAL_NO_VIEWER=1 for a headless run
    (e.g. CI) — falls back to running the checker without any window.

    An optional CLI arg overrides the output path; the default lands in
    ``data/collision_test_report.json`` next to the pose database.
    """
    _reexec_under_mjpython_if_needed()

    checker = CollisionChecker()
    viewer: mujoco.viewer.Handle | None = None
    if os.environ.get("CORAL_NO_VIEWER") != "1":
        try:
            viewer = mujoco.viewer.launch_passive(checker.model, checker.data)
            logger.info("MuJoCo viewer window opened")
        except Exception as e:
            logger.warning(f"Native viewer unavailable ({e}); running headless")

    report = run_collision_test(checker, viewer)

    out_arg = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
    if out_arg:
        out_path = Path(out_arg)
    else:
        # collision_test.py lives at src/coral_agent/collision/ — four levels
        # up from the project root.
        out_path = Path(__file__).parent.parent.parent.parent / "data" / "collision_test_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    verdict = "AT LEAST ONE COLLISION" if report["any_collision"] else "all clear"
    logger.info(f"Collision test complete — {verdict}. Report saved to {out_path}")

    if viewer is not None:
        logger.info("Viewer open — close the window to exit.")
        while viewer.is_running():
            viewer.sync()
            time.sleep(0.1)
        viewer.close()


if __name__ == "__main__":
    main()
