"""Health endpoints for the status lights."""

from fastapi import APIRouter, HTTPException

from app.state import state

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/sim/health")
async def sim_health() -> dict[str, str]:
    """OK only while the MuJoCo simulator exists and its physics loop runs."""
    if state.simulator is None or not state.simulator.is_running():
        raise HTTPException(status_code=503, detail="simulator not running")
    return {"status": "ok"}
