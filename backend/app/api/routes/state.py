"""Demo state endpoints."""

from fastapi import APIRouter

from pydantic import BaseModel

from app.schemas.requests import StateRequest
from app.services.motion import _get_robot_state
from app.follow_controller import gentle_follow_enabled, set_gentle_follow
from app.vision.pose_to_robot import hipless_arms_enabled, set_hipless_arms

router = APIRouter()

_demo_state: str = "IDLE"


@router.post("/state")
async def demo_set_state(req: StateRequest) -> dict[str, str]:
    """Best-effort lock/unlock — the sim has no hard locks, so just record it."""
    global _demo_state
    _demo_state = req.mode
    return {"state": _demo_state}


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
