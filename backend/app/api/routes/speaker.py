"""TTS endpoint for the main CORAL backend.

Returns MP3 audio for a given text string. This endpoint is separate from
the legacy speaker server (port 5002) so callers can get OpenAI TTS audio
without requiring a second service.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.services.tts import generate_speech, tts_enabled

router = APIRouter()


class SpeakRequest(BaseModel):
    text: str


@router.post("/speak")
async def speak(req: SpeakRequest) -> Response:
    """Synthesize ``text`` and return the audio bytes."""
    if not tts_enabled():
        raise HTTPException(status_code=503, detail="TTS is not enabled")

    audio = generate_speech(req.text)
    if audio is None:
        raise HTTPException(status_code=500, detail="TTS generation failed")

    return Response(content=audio, media_type="audio/mpeg")


@router.get("/speak/health")
async def speaker_health() -> dict:
    return {"status": "ok", "tts_enabled": tts_enabled()}
