"""Robot state and follow-mode settings endpoints."""

from app.services.follow import gentle_follow_enabled, set_gentle_follow
from app.services.motion import _get_robot_state
from app.vision.pose_to_robot import hipless_arms_enabled, set_hipless_arms
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

@router.get("/joint_states")
async def get_joint_states() -> dict[str, dict[str, float]]:
    """Return the current robot joint states in radians."""
    return {"joint_states": _get_robot_state()}


class HiplessArmsRequest(BaseModel):
    enabled: bool
    # Slower, smoother following so the simulated robot doesn't topple.
    # Defaults to the same value as `enabled`.
    gentle: bool | None = None


@router.post("/follow/hipless-arms")
async def set_follow_hipless_arms(req: HiplessArmsRequest) -> dict[str, bool]:
    """Switch "follow my movement" to the Rock-Paper-Scissors settings: drive the
    head and arms without seeing the hips, and move gently.

    Rock-Paper-Scissors turns this on while it is open and off again on exit.
    """
    set_hipless_arms(req.enabled)
    set_gentle_follow(req.enabled if req.gentle is None else req.gentle)
    return {"enabled": hipless_arms_enabled(), "gentle": gentle_follow_enabled()}
