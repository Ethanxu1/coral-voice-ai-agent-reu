"""Walk buttons: POST /walk/step {direction: 1 | -1}, POST /walk/stop.

The real robot only (the simulator has no walking engine). See
app/services/walk_buttons.py for how long a click walks and the safety
limits.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import walk_buttons
from app.state import state

router = APIRouter(prefix="/walk", tags=["walk"])


class WalkStepRequest(BaseModel):
    direction: Literal[1, -1]


@router.post("/step")
async def walk_step(request: WalkStepRequest):
    if state.robot_mode not in ("robot", "hardware"):
        raise HTTPException(
            status_code=409,
            detail="Walking needs the real robot. Start the app with ./run.sh -live.",
        )
    note = walk_buttons.travel_message(await walk_buttons.robot_walk_status(), request.direction)
    await walk_buttons.buttons.start(request.direction)
    return {"walking": "forward" if request.direction > 0 else "backward",
            "seconds": walk_buttons.BUTTON_WALK_S, "note": note}


@router.post("/stop")
async def walk_stop():
    await walk_buttons.buttons.stop()
    return {"walking": None}
