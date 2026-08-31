"""Health and readiness endpoints."""

import os
from pathlib import Path

from fastapi import APIRouter

from app import resource_path
from app.config import OPENAI_API_KEY, TTS_IS_ENABLED
from app.services.transcription import _get_whisper_model

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict:
    """Readiness probe: reports whether the backend can serve a full session.

    Checks asset presence, Whisper load, TTS configuration, and DB writability.
    The Electron launcher can poll this instead of plain /health for a stronger
    startup guarantee.
    """
    checks: dict[str, bool | str] = {"status": "ok"}

    # MuJoCo robot asset tree must be present.
    assets_dir = resource_path.repo_root() / "assets" / "ainex"
    checks["assets_present"] = assets_dir.is_dir() and any(assets_dir.rglob("*.xml"))

    # Whisper model is pre-loaded during lifespan; this call is cached and cheap.
    try:
        _get_whisper_model()
        checks["whisper_ready"] = True
    except Exception as exc:
        checks["whisper_ready"] = False
        checks["whisper_error"] = str(exc)

    # TTS is auto-enabled when an OpenAI key is present. Warn if it should work
    # but the key is missing.
    checks["tts_enabled"] = TTS_IS_ENABLED
    checks["tts_key_present"] = bool(OPENAI_API_KEY)
    if TTS_IS_ENABLED and not OPENAI_API_KEY:
        checks["tts_error"] = "TTS is enabled but OPENAI_API_KEY is missing"

    # Pose DB directory must be writable so saved poses persist.
    db_path = Path(resource_path.user_data_dir()) / "poses.db"
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        checks["db_writable"] = os.access(db_path.parent, os.W_OK)
    except Exception as exc:
        checks["db_writable"] = False
        checks["db_error"] = str(exc)

    all_ok = all(
        v is True
        for k, v in checks.items()
        if k not in ("status", "tts_error", "whisper_error", "db_error")
    )
    checks["status"] = "ok" if all_ok else "degraded"
    return checks
