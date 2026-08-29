"""Demo state endpoint."""

from fastapi import APIRouter

from app.schemas.requests import StateRequest

router = APIRouter()

_demo_state: str = "IDLE"


@router.post("/state")
async def demo_set_state(req: StateRequest) -> dict[str, str]:
    """Best-effort lock/unlock — the sim has no hard locks, so just record it."""
    global _demo_state
    _demo_state = req.mode
    return {"state": _demo_state}
