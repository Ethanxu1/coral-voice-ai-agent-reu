"""Standing-balance demo endpoints — sim only, for watching
SimBalanceLoop (backend/app/balance/sim_loop.py) recover from a push in
the browser's 3D viewer (/ws/sim). See docs/balance-controller-progress.md.

Deliberately separate from robot control's usual endpoints: this doesn't
go through dispatch_servo_commands or the sim/hardware toggle — it writes
straight to the simulator's own joints, the same way the balance loop
will keep doing continuously once started. Off by default; nothing here
runs or moves anything until POST /balance/start.
"""

from fastapi import APIRouter, HTTPException

from app.schemas.requests import PushRequest
from app.state import state

router = APIRouter()


@router.post("/balance/start")
async def balance_start() -> dict:
    """Start the background balance loop. Not an error if already
    running — a caller doesn't need to check status first."""
    if state.balance_loop is None:
        raise HTTPException(status_code=503, detail="balance loop not available")
    was_running = state.balance_loop.running
    state.balance_loop.start()
    return {"running": True, "already_running": was_running}


@router.post("/balance/stop")
async def balance_stop() -> dict:
    if state.balance_loop is None:
        raise HTTPException(status_code=503, detail="balance loop not available")
    state.balance_loop.stop()
    return {"running": False}


@router.get("/balance/status")
async def balance_status() -> dict:
    if state.balance_loop is None:
        return {"available": False, "running": False, "tick_count": 0, "last_error": None}
    return {
        "available": True,
        "running": state.balance_loop.running,
        "tick_count": state.balance_loop.tick_count,
        "last_error": state.balance_loop.last_error,
    }


@router.post("/balance/push")
async def balance_push(req: PushRequest) -> dict:
    """Give the simulator a one-time shove to test recovery against —
    works whether or not the balance loop is currently running, so you
    can push first and watch it fall, then start the loop and push again
    to compare."""
    if state.simulator is None:
        raise HTTPException(status_code=503, detail="simulator not available")
    state.simulator.push_disturbance(
        roll_rad_per_s=req.roll_rad_per_s, pitch_rad_per_s=req.pitch_rad_per_s
    )
    return {"pushed": True, "roll_rad_per_s": req.roll_rad_per_s, "pitch_rad_per_s": req.pitch_rad_per_s}
