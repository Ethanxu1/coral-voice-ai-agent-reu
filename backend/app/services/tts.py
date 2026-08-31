"""OpenAI text-to-speech service for CORAL.

Provides buffered MP3 generation for short assistant responses. Failures
are logged and swallowed so a TTS hiccup never blocks robot motion.
"""

from __future__ import annotations

from loguru import logger

from app.config import (
    OPENAI_API_KEY,
    TTS_ENABLED,
    TTS_FORMAT,
    TTS_IS_ENABLED,
    TTS_MAX_CHARS,
    TTS_MODEL,
    TTS_VOICE,
)

# Import the base OpenAI client, not the Langfuse-wrapped one — TTS does
# not need tracing and the wrapper may not expose audio.speech cleanly.
from openai import OpenAI


class TTSError(Exception):
    """TTS generation failed; callers should fall back to silent text."""


# Lazily initialized client so importing this module never blocks startup.
_client: OpenAI | None = None


def _get_client() -> OpenAI | None:
    global _client
    if _client is None and OPENAI_API_KEY:
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def tts_enabled() -> bool:
    """Return whether TTS is configured and available."""
    return TTS_IS_ENABLED and OPENAI_API_KEY != ""


def generate_speech(text: str) -> bytes | None:
    """Synthesize ``text`` into audio bytes using OpenAI TTS.

    Returns ``None`` when TTS is disabled, the text is empty/too long, or
    the OpenAI call fails. This is intentional: TTS is a nicety and must
    never crash the chat/motion pipeline.
    """
    if not tts_enabled():
        return None

    if not text or not text.strip():
        return None

    if len(text) > TTS_MAX_CHARS:
        logger.warning(
            f"TTS text exceeds {TTS_MAX_CHARS} chars ({len(text)}); truncating"
        )
        text = text[:TTS_MAX_CHARS]

    client = _get_client()
    if client is None:
        logger.warning("TTS enabled but OpenAI client could not be initialized")
        return None

    try:
        response = client.audio.speech.create(
            model=TTS_MODEL,
            voice=TTS_VOICE,  # type: ignore[arg-type]
            input=text,
            response_format=TTS_FORMAT,  # type: ignore[arg-type]
        )
        data = response.content
        logger.debug(f"Generated {len(data)} bytes of {TTS_FORMAT} TTS audio")
        return data
    except Exception as e:
        logger.warning(f"OpenAI TTS failed: {e}")
        return None


def invalidate_client() -> None:
    """Reset the cached OpenAI client (useful in tests)."""
    global _client
    _client = None
