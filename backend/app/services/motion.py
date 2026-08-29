"""Robot motion dispatch, waypoint execution, and safety checks."""

from __future__ import annotations

import asyncio
import math
from typing import Any, Awaitable

from loguru import logger

from app.robot.angle_utils import rad_to_servo_units, servo_units_to_rad, speed_to_duration_ms
from app.robot.hardware_controller import AiNexHardwareController
from app.robot.interface import ServoCommand
from app.robot.servo_config import SERVO_ID_MAP
from app.robot.sim_controller import SimController
from app.simulator import AiNexSimulator
from app.validation import ValidationResult, validate_waypoint
from app.state import state


# Hardware travel time for a reset/stand. The sim teleports into the stand
# keyframe, but a physical robot has to be animated there, and a full-body move
# needs a longer, gentler interval than a single-joint nudge.
RESET_TO_STAND_MS = 1000


def convert_state_to_degrees(state: dict[str, float]) -> dict[str, float]:
    return {joint: round(math.degrees(value), 1) for joint, value in state.items()}


class RobotServerUnavailable(RuntimeError):
    """The requested physical-robot dispatch could not be completed."""


class Waypoint:
    def __init__(
        self,
        joints: dict[str, float],
        speed: float = 1.0,
        primitive_name: str | None = None,
        angle: float | None = None,
        direction: str | None = None,
    ):
        self.joints = joints
        self.speed = max(0.1, min(speed, 8.0))
        self.primitive_name = primitive_name
        self.angle = angle
        self.direction = direction
        self.validation_result: ValidationResult | None = None


def _get_robot_state() -> dict[str, float]:
    """Return current joint states.

    Hardware is only trusted when it's known to match the last dispatched
    move (``state.hardware_in_sync``) — otherwise a pose composed sim_only would
    report the physical robot's stale, unrelated position instead of what was
    actually built.
    """
    if (
        state.robot_mode in ("robot", "hardware")
        and state.hardware_dispatcher is not None
        and state.hardware_in_sync
    ):
        try:
            return state.hardware_dispatcher.get_joint_states()
        except Exception as e:
            logger.debug(f"Hardware joint-state read failed, falling back to sim: {e}")
    if state.simulator is not None:
        return state.simulator.get_all_joint_states()
    return {}


def _sync_sim_to_hardware() -> None:
    """Copy the physical robot's current joint positions into the simulator
    so the viewer starts mirroring the real robot's pose."""
    if state.simulator is None or state.hardware_dispatcher is None:
        return
    try:
        physical_state = state.hardware_dispatcher.get_joint_states()
    except Exception as e:
        logger.warning(f"Could not read physical joint states for sim sync: {e}")
        return
    synced = 0
    for joint, rad in physical_state.items():
        if joint in state.simulator.JOINT_NAMES:
            state.simulator.set_joint_position(joint, rad)
            synced += 1
    state.hardware_in_sync = True
    logger.info(f"Synced simulator to {synced} physical joint positions")


def collision_checked_targets(
    sim: AiNexSimulator | None, target_joints: dict[str, float], context: str
) -> tuple[dict[str, float], dict[str, Any]]:
    """Run both safety checks on target_joints from the sim's current state.

    1. Kinematic self-collision (CollisionChecker): clamps every moving joint
       back to the last collision-free fraction of the motion.
    2. Dynamic fall check (StabilityChecker): shadow-settles the (clamped)
       target under gravity; if the robot's head ends below the fall threshold
       (it toppled), the ENTIRE move is blocked — 0% executed, the returned
       targets are the sim's current joints — since there's no safe fraction
       of falling over.

    Returns (safe_targets, safety_report). safety_report is JSON-ready so
    endpoints can pass it straight to the frontend:
      {"fall_blocked": bool, "collision_clamped": bool, "safe_fraction": float,
       "bad_pairs": [...], "head_z": float|None, "threshold_z": float|None}
    Checks are individually skipped (no-op) when their checker is disabled.
    """
    report: dict[str, Any] = {
        "fall_blocked": False,
        "collision_clamped": False,
        "safe_fraction": 1.0,
        "bad_pairs": [],
        "head_z": None,
        "threshold_z": None,
    }
    if sim is None or not target_joints:
        return target_joints, report
    current = sim.get_all_joint_states()

    safe_joints = target_joints
    if state.collision_checker is not None:
        safe_joints, safe_frac, bad_pairs = state.collision_checker.check_trajectory(
            current, target_joints
        )
        if safe_frac < 1.0:
            logger.warning(
                f"{context}: collision risk ({bad_pairs}); reduced to {safe_frac:.0%} of target"
            )
            report.update(collision_clamped=True, safe_fraction=safe_frac, bad_pairs=bad_pairs)

    if state.stability_checker is not None:
        fall = state.stability_checker.check_fall(safe_joints, current)
        report.update(head_z=fall["head_z"], threshold_z=fall["threshold_z"])
        if fall["fell"]:
            logger.warning(
                f"{context}: FALL RISK — settled head_z={fall['head_z']} < "
                f"threshold {fall['threshold_z']}; move blocked entirely (0%)"
            )
            report.update(fall_blocked=True, safe_fraction=0.0)
            return dict(current), report

    return safe_joints, report


async def dispatch_servo_commands(
    commands: list[ServoCommand], sim_only: bool | None = None
) -> None:
    """Send commands to the simulator and, when requested, the physical robot.

    ``sim_only`` is set by an approved frontend motion request. ``None`` keeps
    the existing server-mode behavior for background flows such as following.
    """
    if not commands:
        return
    dispatches: list[Awaitable[Any]] = []
    if state.sim_dispatcher is not None:
        dispatches.append(asyncio.to_thread(state.sim_dispatcher.send_commands, commands))
    send_to_hardware = sim_only is False or (
        sim_only is None and state.robot_mode in ("robot", "hardware")
    )
    if send_to_hardware:
        if state.hardware_dispatcher is None:
            state.hardware_dispatcher = await asyncio.to_thread(AiNexHardwareController)
        dispatches.append(asyncio.to_thread(state.hardware_dispatcher.send_commands, commands))
    if dispatches:
        results = await asyncio.gather(*dispatches, return_exceptions=True)
        # Hardware is only in sync with what was just built if this dispatch
        # actually reached it without error — a sim_only move (or a failed
        # hardware send) leaves hardware's joints stale relative to the sim.
        state.hardware_in_sync = send_to_hardware and not isinstance(results[-1], Exception)
        if send_to_hardware and isinstance(results[-1], Exception):
            raise RobotServerUnavailable("robot server could not be reached") from results[-1]
        if isinstance(results[0], Exception):
            raise results[0]
    else:
        state.hardware_in_sync = send_to_hardware


async def _execute_on_hardware_if_connected(
    joints: dict[str, float], duration_ms: int = 1000
) -> None:
    """Physically strike ``joints`` on the robot when the backend is actually
    connected to hardware — used right after a pose is saved, so "saving"
    doubles as "showing the child what was saved". Deliberately ignores
    ``sim_only``/the frontend toggle (passes ``sim_only=None``): saving and
    demonstrating are the two actions that are always allowed to reach
    hardware once connected — see the 2026-08-27 fix. No-ops in sim mode,
    and a hardware-server hiccup is logged rather than raised, since this is
    a nicety on top of an already-completed save, not something that should
    fail the save itself.
    """
    if state.robot_mode not in ("robot", "hardware") or state.simulator is None:
        return
    safe_joints, _safety = collision_checked_targets(
        state.simulator, joints, "pose save/demonstrate"
    )
    commands = [
        ServoCommand(
            servo_id=SERVO_ID_MAP[joint],
            position=rad_to_servo_units(rad),
            duration_ms=duration_ms,
        )
        for joint, rad in safe_joints.items()
        if joint in SERVO_ID_MAP
    ]
    try:
        await dispatch_servo_commands(commands, sim_only=None)
    except RobotServerUnavailable as e:
        logger.warning(f"Could not execute pose on hardware: {e}")


async def execute_waypoints(
    simulator: AiNexSimulator, waypoints: list[Waypoint], sim_only: bool | None = None
) -> list[dict]:
    """Execute a sequence of waypoints through the hardware abstraction layer.

    Each waypoint is converted to ServoCommands (Hiwonder units + duration_ms)
    and dispatched to the controller, which handles concurrent joint interpolation.
    Sequential waypoints run one after the other.

    Returns a list of executed waypoint info. Each entry carries a per-waypoint
    ``safety`` report in the same JSON shape as collision_checked_targets, so the
    caller can tell the user what the checks did (see aggregate_safety).
    """
    executed = []

    for i, waypoint in enumerate(waypoints):
        duration_ms = speed_to_duration_ms(waypoint.speed)
        safety: dict[str, Any] = {
            "fall_blocked": False,
            "collision_clamped": False,
            "safe_fraction": 1.0,
            "bad_pairs": [],
        }

        if state.collision_checker is not None:
            current = simulator.get_all_joint_states()
            safe_joints, safe_frac, bad_pairs = state.collision_checker.check_trajectory(
                current, waypoint.joints
            )
            if safe_frac < 1.0:
                logger.warning(
                    f"Waypoint {i} collision risk ({bad_pairs}); "
                    f"reduced to {safe_frac:.0%} of target"
                )
                waypoint.joints = safe_joints
                safety.update(
                    collision_clamped=True, safe_fraction=safe_frac, bad_pairs=bad_pairs
                )

        # Fall check: if this waypoint would topple the robot, skip it entirely
        # (0% — hold the current pose) rather than clamping; there's no safe
        # fraction of falling over.
        if state.stability_checker is not None:
            current = simulator.get_all_joint_states()
            fall = state.stability_checker.check_fall(waypoint.joints, current)
            if fall["fell"]:
                logger.warning(
                    f"Waypoint {i} FALL RISK — settled head_z={fall['head_z']} < "
                    f"threshold {fall['threshold_z']}; waypoint blocked entirely (0%)"
                )
                waypoint.joints = dict(current)
                safety.update(fall_blocked=True, safe_fraction=0.0)

        commands = []
        for joint_name, rad in waypoint.joints.items():
            servo_id = SERVO_ID_MAP.get(joint_name)
            if servo_id is None:
                logger.warning(f"No servo ID mapping for joint: {joint_name}")
                continue
            commands.append(
                ServoCommand(
                    servo_id=servo_id,
                    position=rad_to_servo_units(rad),
                    duration_ms=duration_ms,
                )
            )

        await dispatch_servo_commands(commands, sim_only=sim_only)

        executed.append(
            {
                "waypoint_index": i,
                "primitive_name": waypoint.primitive_name,
                "angle": waypoint.angle,
                "joints": waypoint.joints,
                "speed": waypoint.speed,
                "safety": safety,
            }
        )
        logger.info(
            f"Executed waypoint {i}: {waypoint.primitive_name or 'direct'} "
            f"angle={waypoint.angle} speed={waypoint.speed} duration_ms={duration_ms}"
        )

    return executed


def aggregate_safety(executed: list[dict]) -> dict[str, Any]:
    """Collapse per-waypoint safety reports into one verdict for the whole move.

    A multi-waypoint plan is a single action from the user's point of view, so
    the strictest outcome wins: blocked if any waypoint toppled the robot,
    clamped if any was pulled back, and the reported fraction is the tightest
    clamp applied. Same JSON shape as collision_checked_targets' report, so the
    frontend parses /move responses and chat responses with one code path.
    """
    merged: dict[str, Any] = {
        "fall_blocked": False,
        "collision_clamped": False,
        "safe_fraction": 1.0,
        "bad_pairs": [],
    }
    for entry in executed:
        safety = entry.get("safety")
        if not safety:
            continue
        merged["fall_blocked"] |= bool(safety.get("fall_blocked"))
        merged["collision_clamped"] |= bool(safety.get("collision_clamped"))
        merged["safe_fraction"] = min(
            merged["safe_fraction"], float(safety.get("safe_fraction", 1.0))
        )
        for pair in safety.get("bad_pairs") or []:
            if pair not in merged["bad_pairs"]:
                merged["bad_pairs"].append(pair)
    return merged


async def execute_parallel_tracks(
    simulator: AiNexSimulator,
    tracks: list[list[Waypoint]],
    sim_only: bool | None = None,
) -> list[dict]:
    """Execute multiple waypoint tracks concurrently using asyncio.gather.

    Tracks should operate on disjoint joint sets to avoid conflicts.
    """
    results = await asyncio.gather(
        *[execute_waypoints(simulator, track, sim_only=sim_only) for track in tracks]
    )
    return [wp for track_result in results for wp in track_result]
