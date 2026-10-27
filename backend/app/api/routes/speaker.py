"""TTS endpoint: returns OpenAI speech audio for a text string.

For pages that speak outside the /ws chat pipeline. Rock Paper Scissors used it,
but now speaks with the browser's own speech synthesis (frontend audio/speech.ts).
"""

from __future__ import annotations

import asyncio

from app.services.tts import generate_speech, tts_enabled
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

router = APIRouter()


class SpeakRequest(BaseModel):
    text: str


@router.post("/speak")
async def speak(req: SpeakRequest) -> Response:
    """Synthesize ``text`` and return the audio bytes."""
    if not tts_enabled():
        raise HTTPException(status_code=503, detail="TTS is not enabled")

    # The OpenAI call blocks for a second or two: run it off the event loop so
    # robot moves and the sim stream don't stall while CORAL speaks.
    audio = await asyncio.to_thread(generate_speech, req.text)
    if audio is None:
        raise HTTPException(status_code=500, detail="TTS generation failed")

    return Response(content=audio, media_type="audio/mpeg")


@router.get("/speak/health")
async def speaker_health() -> dict:
    return {"status": "ok", "tts_enabled": tts_enabled()}
