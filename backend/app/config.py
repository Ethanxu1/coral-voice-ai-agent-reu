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
# MuJoCo native viewer
# ---------------------------------------------------------------------------
CORAL_MUJOCO_WINDOW = os.getenv("CORAL_MUJOCO_WINDOW", "0").lower() in (
    "true",
    "1",
    "yes",
)
CORAL_NO_VIEWER = os.getenv("CORAL_NO_VIEWER", "0").lower() in ("true", "1", "yes")
