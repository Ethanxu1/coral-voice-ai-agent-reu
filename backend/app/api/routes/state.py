"""Robot state and follow-mode settings endpoints."""

from app.robot.hardware_angle_utils import rad_to_hardware_units
from app.services.follow import gentle_follow_enabled, set_gentle_follow
from app.services.motion import _get_robot_state
from app.state import state
from app.vision.pose_to_robot import hipless_arms_enabled, set_hipless_arms
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

@router.get("/joint_states")
async def get_joint_states() -> dict[str, dict[str, float]]:
    """Return the current robot joint states in radians."""
    return {"joint_states": _get_robot_state()}


@router.get("/joint_states/pulses")
async def get_joint_pulses() -> dict[str, dict[str, int]]:
    """Return the current robot joint states as hardware servo pulses (0-1000),
    the same units /set-pose takes. Rock-Paper-Scissors uses this to save the
    pose the robot reached while following a child as one of its moves."""
    return {
        "pulses": {
            joint: rad_to_hardware_units(rad, joint)
            for joint, rad in _get_robot_state().items()
        }
    }


class HiplessArmsRequest(BaseModel):
    enabled: bool
    # Slower, smoother following so the simulated robot doesn't topple.
    # Defaults to the same value as `enabled`.
    gentle: bool | None = None


class UprightRequest(BaseModel):
    enabled: bool


@router.post("/sim/upright")
async def set_sim_upright(req: UprightRequest) -> dict[str, bool]:
    """Hold the simulated robot's body upright so it can't tip or fall.

    The test pages (Joint test, Pose Tester) turn this on while open and off on
    exit. Sim only — it has no effect on a physical robot.
    """
    if state.simulator is not None:
        state.simulator.set_upright_pinned(req.enabled)
    return {"enabled": req.enabled}


@router.post("/follow/hipless-arms")
async def set_follow_hipless_arms(req: HiplessArmsRequest) -> dict[str, bool]:
    """Switch "follow my movement" to the Rock-Paper-Scissors settings: drive the
    head and arms without seeing the hips, and move gently.

    Rock-Paper-Scissors turns this on while it is open and off again on exit.
    """
    set_hipless_arms(req.enabled)
    set_gentle_follow(req.enabled if req.gentle is None else req.gentle)
    return {"enabled": hipless_arms_enabled(), "gentle": gentle_follow_enabled()}
