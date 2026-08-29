"""Whisper transcription and prompt loading."""

import re
import tempfile
from pathlib import Path

from loguru import logger

from app.config import WHISPER_MODEL_SIZE


_ROUTER_PROMPT_CACHE: str | None = None
_CHAT_PROMPT_CACHE: str | None = None
_WHISPER_PROMPT_CACHE: str | None = None


PROMPTS_DIR = Path(__file__).resolve().parent.parent / "llm" / "prompts"


_whisper_model = None


def get_router_prompt() -> str:
    global _ROUTER_PROMPT_CACHE
    if _ROUTER_PROMPT_CACHE is None:
        _ROUTER_PROMPT_CACHE = (
            PROMPTS_DIR / "router.md"
        ).read_text(encoding="utf-8")
    return _ROUTER_PROMPT_CACHE


def get_chat_prompt() -> str:
    global _CHAT_PROMPT_CACHE
    if _CHAT_PROMPT_CACHE is None:
        _CHAT_PROMPT_CACHE = (
            PROMPTS_DIR / "chat.md"
        ).read_text(encoding="utf-8")
    return _CHAT_PROMPT_CACHE


def get_whisper_prompt() -> str:
    global _WHISPER_PROMPT_CACHE
    if _WHISPER_PROMPT_CACHE is None:
        _WHISPER_PROMPT_CACHE = (
            PROMPTS_DIR / "whisper.md"
        ).read_text(encoding="utf-8")
    return _WHISPER_PROMPT_CACHE


def _get_whisper_model_size() -> str:
    """Return the configured Whisper model size, defaulting to English 'base.en'."""
    size = WHISPER_MODEL_SIZE.strip().lower()
    # Allow plain sizes; default to the English-only variant for short commands.
    if size in ("tiny", "base", "small"):
        return f"{size}.en"
    return size


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        model_size = _get_whisper_model_size()
        logger.info(f"Loading Whisper model ({model_size})...")
        _whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        logger.info("Whisper model loaded.")
    return _whisper_model


# Known Whisper hallucinations that appear on noisy or very short audio.
_HALLUCINATION_RE = re.compile(
    r"\b(?:www\.[\w.-]+\.[a-z]{2,}|https?://\S+|\S+@\S+|\S+\.(?:com|info|org|net|gov|edu))\b",
    re.IGNORECASE,
)


def clean_transcription(text: str) -> str:
    """Strip common Whisper hallucinations and normalize whitespace."""
    # Remove URLs/email-like tokens.
    text = _HALLUCINATION_RE.sub("", text)
    # Collapse repeated words (e.g. "the the the").
    text = re.sub(r"\b(\w+)(\s+\1)+", r"\1", text, flags=re.IGNORECASE)
    # Normalize whitespace.
    text = re.sub(r"\s+", " ", text).strip()
    return text


def transcribe_audio(audio_bytes: bytes) -> str:
    model = _get_whisper_model()
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    try:
        segments, _ = model.transcribe(
            tmp_path,
            language="en",
            no_speech_threshold=0.6,
            initial_prompt=get_whisper_prompt(),
            vad_filter=True,
            condition_on_previous_text=False,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
        )
        raw_text = " ".join(
            seg.text.strip() for seg in segments if seg.no_speech_prob < 0.6
        ).strip()
        return clean_transcription(raw_text)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
