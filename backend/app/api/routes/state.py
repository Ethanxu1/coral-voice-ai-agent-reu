"""Demo state endpoints."""

from fastapi import APIRouter

from app.schemas.requests import StateRequest
from app.services.motion import _get_robot_state

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
