"""Environment-driven settings for the Coral AI agent."""

import os

# Load environment variables from .env files before any settings are read.
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Robot / hardware
# ---------------------------------------------------------------------------
ROBOT_MODE = os.getenv("ROBOT_MODE", "sim")
ROBOT_IP = os.getenv("ROBOT_IP", "192.168.8.219")
ROBOT_AGENT_PORT = int(os.getenv("ROBOT_AGENT_PORT", "9000"))

# ---------------------------------------------------------------------------
# Vision server
# ---------------------------------------------------------------------------
VISION_BASE = os.getenv("VISION_BASE", "http://localhost:8001")

# ---------------------------------------------------------------------------
# Speech-to-text
# ---------------------------------------------------------------------------
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")

# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------
ENABLE_COLLISION_CHECK = os.getenv("ENABLE_COLLISION_CHECK", "true").lower() in (
    "true",
    "1",
    "yes",
)
ENABLE_FALL_CHECK = os.getenv("ENABLE_FALL_CHECK", "true").lower() in (
    "true",
    "1",
    "yes",
)

# ---------------------------------------------------------------------------
# Langfuse tracing
# ---------------------------------------------------------------------------
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")

# ---------------------------------------------------------------------------
# Text-to-speech (OpenAI)
# ---------------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TTS_ENABLED = os.getenv("TTS_ENABLED", "auto").lower()
# "auto" enables TTS only when an OpenAI API key is present.
TTS_IS_ENABLED = TTS_ENABLED in ("true", "1", "yes") or (
    TTS_ENABLED == "auto" and bool(OPENAI_API_KEY)
)
# "coral" reads as warm/friendly (vs. e.g. "nova"'s brighter, more neutral
# tone) and "tts-1-hd" is the higher-fidelity model — chosen for a young,
# elementary-school audience. speed=1.05 keeps replies lively without
# sounding rushed. All three are overridable via env for a different venue.
TTS_VOICE = os.getenv("TTS_VOICE", "coral")
TTS_MODEL = os.getenv("TTS_MODEL", "tts-1-hd")
TTS_FORMAT = os.getenv("TTS_FORMAT", "mp3")
TTS_SPEED = float(os.getenv("TTS_SPEED", "1.05"))
TTS_MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "4096"))

# ---------------------------------------------------------------------------
# MuJoCo native viewer
# ---------------------------------------------------------------------------
CORAL_MUJOCO_WINDOW = os.getenv("CORAL_MUJOCO_WINDOW", "0").lower() in (
    "true",
    "1",
    "yes",
)
CORAL_NO_VIEWER = os.getenv("CORAL_NO_VIEWER", "0").lower() in ("true", "1", "yes")

# ---------------------------------------------------------------------------
# Vision / pose retargeting
# ---------------------------------------------------------------------------
# Leg tracking is experimental and can be unstable in live demos. Default to
# disabled so the robot only mirrors the upper body, head, and hips; set to
# "true" to re-enable continuous leg retargeting.
ENABLE_LEG_TRACKING = os.getenv("CORAL_ENABLE_LEG_TRACKING", "false").lower() in (
    "true",
    "1",
    "yes",
)

# ---------------------------------------------------------------------------
# Server binding
# ---------------------------------------------------------------------------
# Default to localhost for school/Electron deployments so the backend is not
# exposed on the classroom network. Docker/containerized runs should set
# CORAL_HOST=0.0.0.0 explicitly.
CORAL_HOST = os.getenv("CORAL_HOST", "127.0.0.1")
