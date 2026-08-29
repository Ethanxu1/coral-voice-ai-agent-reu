"""Motion, pose, and saved-pose API routes."""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger

from app.data.pose_db import get_pose, list_pose_names, save_pose
from app.robot.angle_utils import rad_to_servo_units, servo_units_to_rad
from app.robot.hardware_angle_utils import hardware_units_to_rad
from app.robot.interface import ServoCommand
from app.robot.servo_config import JOINT_NAME_MAP, SERVO_ID_MAP
from app.schemas.requests import MoveRequest, PlayPoseRequest, SaveCurrentPoseRequest, SetPoseRequest
from app.services.motion import (
    RESET_TO_STAND_MS,
    RobotServerUnavailable,
    _execute_on_hardware_if_connected,
    _get_robot_state,
    collision_checked_targets,
    dispatch_servo_commands,
)
from app.state import state

router = APIRouter()


@router.post("/move")
async def demo_move(request: MoveRequest) -> dict[str, Any]:
    """Execute raw servo commands on the simulator, optionally with hardware.

    Used by the demo's pose-mimicry path: the frontend fetches servo commands
    from the vision server's /map-features (landmark retargeting) and posts them
    here to drive the robot.

    Landmark retargeting has no notion of self-collision, so before dispatch we
    shadow-roll the combined target through the collision checker and clamp any
    servo whose commanded pose would drive it into another link.

    Decodes with servo_units_to_rad (the uniform 500-centre sim map), not
    hardware_units_to_rad — /map-features always encodes with rad_to_servo_units,
    the same uniform map, regardless of sim/hardware mode.
    """
    if state.simulator is None:
        return {"status": "error", "detail": "simulator not initialized"}

    moves = request.moves
    target_joints = {
        joint: servo_units_to_rad(m.position)
        for m in moves
        if (joint := JOINT_NAME_MAP.get(m.servo_id)) is not None
    }
    target_joints, safety = collision_checked_targets(state.simulator, target_joints, "/move")

    # Fall check failed → the move is unsafe as a whole. Dispatch nothing (0%
    # of the move) and let the caller report the blocked result to the user.
    if safety["fall_blocked"]:
        return {"status": "blocked", "count": 0, "safety": safety}

    commands = []
    for m in moves:
        joint = JOINT_NAME_MAP.get(m.servo_id)
        position = (
            rad_to_servo_units(target_joints[joint])
            if joint in target_joints
            else m.position
        )
        commands.append(
            ServoCommand(
                servo_id=m.servo_id,
                position=position,
                duration_ms=max(100, m.duration_ms),
            )
        )

    if state.sim_dispatcher is None:
        raise HTTPException(status_code=503, detail="simulation server is not initialized")

    try:
        await dispatch_servo_commands(commands, sim_only=None)
    except RobotServerUnavailable as e:
        logger.warning(f"/move: robot server unavailable: {e}")
        raise HTTPException(status_code=503, detail="robot server could not be reached")
    return {"status": "done", "count": len(commands), "safety": safety}


@router.post("/set-pose")
async def set_pose(req: SetPoseRequest) -> dict[str, Any]:
    """Apply a raw {joint: hardware_pulse} pose to the sim (testing tool).

    Accepts the exact pulse dicts authored in motions.py. Each pulse is a
    *hardware* servo unit, so it's converted to sim radians with
    hardware_units_to_rad. The combined target is then shadow-rolled through the
    collision checker (same as /move) before set_joint_position applies it.
    Sim only; unknown joints are reported back.
    """
    if state.simulator is None:
        return {"status": "error", "detail": "simulator not initialized"}

    applied: list[str] = []
    skipped: list[str] = []

    target_joints: dict[str, float] = {}
    for joint, pulse in req.pulses.items():
        if joint not in SERVO_ID_MAP:
            skipped.append(joint)
            continue
        try:
            target_joints[joint] = hardware_units_to_rad(int(pulse), joint)
        except Exception as e:  # bad pulse value — skip, keep going
            logger.debug(f"/set-pose: skip joint {joint}: {e}")
            skipped.append(joint)

    if not req.skip_collision_check:
        target_joints, _safety = collision_checked_targets(
            state.simulator, target_joints, "/set-pose"
        )

    for joint, rad in target_joints.items():
        try:
            state.simulator.set_joint_position(joint, rad)
            applied.append(joint)
        except Exception as e:  # unknown sim joint — skip, keep going
            logger.debug(f"/set-pose: skip joint {joint}: {e}")
            skipped.append(joint)

    return {"status": "done", "applied": applied, "skipped": skipped}


@router.post("/reset")
async def reset_pose() -> dict[str, Any]:
    """Snap the sim back to the stand pose and, in robot mode, animate the
    hardware there smoothly."""
    if state.simulator is None:
        return {"status": "error", "detail": "simulator not initialized"}

    await asyncio.to_thread(state.simulator.reset_pose)

    if state.hardware_dispatcher is not None:
        stand = state.simulator.get_stand_joint_positions()
        commands = [
            ServoCommand(
                servo_id=sid,
                position=rad_to_servo_units(rad),
                duration_ms=RESET_TO_STAND_MS,
            )
            for joint, rad in stand.items()
            if (sid := SERVO_ID_MAP.get(joint)) is not None
        ]
        if commands:
            try:
                await dispatch_servo_commands(commands, sim_only=None)
            except RobotServerUnavailable as e:
                logger.warning(f"/reset: robot server unavailable: {e}")

    return {"status": "done"}


@router.get("/poses")
async def list_poses_endpoint() -> dict[str, list[str]]:
    """List all saved pose names."""
    names = list_pose_names()
    return {"poses": names}


@router.post("/poses/save-current")
async def save_current_pose_endpoint(req: SaveCurrentPoseRequest) -> dict[str, str]:
    """Save the current robot joint state under the given name."""
    joints = _get_robot_state()
    clean_name = req.name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    save_pose(clean_name, joints)
    await _execute_on_hardware_if_connected(joints)
    return {"name": clean_name, "status": "saved"}


@router.post("/poses/play")
async def play_pose_endpoint(req: PlayPoseRequest) -> dict[str, Any]:
    """Strike a saved pose directly by name, without the LLM motion planner."""
    clean_name = req.name.strip()
    joints = get_pose(clean_name)
    if joints is None:
        raise HTTPException(status_code=404, detail=f"Pose '{clean_name}' not found")
    joints, _safety = collision_checked_targets(
        state.simulator, joints, f"/poses/play '{clean_name}'"
    )
    duration_ms = max(1, req.duration_ms)
    commands = [
        ServoCommand(
            servo_id=SERVO_ID_MAP[joint],
            position=rad_to_servo_units(rad),
            duration_ms=duration_ms,
        )
        for joint, rad in joints.items()
        if joint in SERVO_ID_MAP
    ]
    await dispatch_servo_commands(commands, sim_only=req.sim_only)
    logger.info(f"Played saved pose '{clean_name}' ({len(commands)} joints)")
    return {"name": clean_name, "joints_played": len(commands), "status": "played"}
