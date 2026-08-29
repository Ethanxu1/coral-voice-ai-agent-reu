"""Intent classification endpoint."""

import asyncio
from datetime import datetime

from fastapi import APIRouter
from langfuse import get_client, observe, propagate_attributes

from app.data.pose_db import list_pose_names
from app.llm.config import LLM_MODEL
from app.llm.intent_classifier import classify_intent
from app.schemas.requests import IntentRequest
from app.services.motion import _get_robot_state, convert_state_to_degrees
from app.validation import describe_joint_state

router = APIRouter()


@router.post("/classify-intent")
@observe(name="classify_intent")
async def classify_intent_endpoint(req: IntentRequest) -> dict:
    """Classify user intent for the refined demo."""
    session_id = req.session_id or f"intent-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    langfuse = get_client()
    with propagate_attributes(
        session_id=session_id,
        user_id="coral-user",
        tags=["coral-agent", "intent-classification"],
    ):
        langfuse.update_current_span(input=req.text)

        robot_state = await asyncio.to_thread(_get_robot_state)
        state_degrees = convert_state_to_degrees(robot_state)
        state_description = describe_joint_state(robot_state)
        saved_names = list_pose_names()

        result = classify_intent(
            text=req.text,
            follow_active=req.follow_active,
            state_degrees=state_degrees,
            state_description=state_description,
            saved_names=saved_names,
            history=req.history,
            model=LLM_MODEL,
        )

        langfuse.update_current_span(output=result)
        return result
