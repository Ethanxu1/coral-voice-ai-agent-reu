"""Environment-driven settings for the Coral AI agent."""

import os

# Load environment variables from .env files before any settings are read.
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Robot / hardware
# ---------------------------------------------------------------------------
ROBOT_MODE = os.getenv("ROBOT_MODE", "sim")
# Simulated servo stiffness: "stiff" (as authored) or "hardware" (leg servos
# give under load like the real robot's -- see app/simulator/servo_model.py).
SIM_SERVO_MODEL = os.getenv("CORAL_SIM_SERVO_MODEL", "stiff")
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
# CBF safety filter on the live-follow mimicry stream
# (docs/cbf-whole-body-progress.md).
#
# DEFAULT OFF as of 2026-09-29. It is not fit to run yet: verified
# against real physics, it false-positives on ASYMMETRIC single-joint
# poses — which is exactly what live mimicry produces. Measured
# r_hip_roll verdicts went unsafe / unsafe / SAFE / unsafe across
# 0.0625 / 0.125 / 0.25 / 0.5 rad while the robot stayed up in all
# four. That is noise, not a threshold. In a live session it held back
# 100% of frames and toppled the robot.
#
# Earlier validation (Phase 2.5, 12/12 against dynamics) only covered
# SYMMETRIC leg poses, which behave; that is why this got through.
#
# Set to "true" to re-enable for development. The ankle/hip balance
# controller is separate and unaffected by this flag either way.
ENABLE_FOLLOW_SAFETY = os.getenv("CORAL_ENABLE_FOLLOW_SAFETY", "false").lower() in (
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
# Enabled 2026-09-29, now that LEG_MIMICRY_MAX_TRAVEL below caps how far a
# leg movement actually goes. It was disabled because an uncapped
# retargeted leg lift topples the robot — verified: roll -102 deg
# uncapped vs -16 deg capped at 0.5, and -104 vs -6 with vision jitter
# injected (docs/cbf-whole-body-progress.md Phase 2.7).
#
# Set to "false" to go back to upper-body-only mimicry.
# Leg mimicry on the REAL robot in follow mode. Off: legs and ankles hold
# stand whenever follow drives the hardware; arms still follow. 2026-10-02:
# arms-only follow, the camera misread lost legs as raised, the leg-lift
# controller slid the hips and the robot tipped -- one-foot stance sags ~10
# deg on hardware and isn't solved yet (docs/cbf-whole-body-progress.md
# Phase 2.17). The sim always keeps leg mimicry.
HARDWARE_LEG_MIMICRY = os.getenv("CORAL_HARDWARE_LEG_MIMICRY", "false").lower() in (
    "true",
    "1",
    "yes",
)
ENABLE_LEG_TRACKING = os.getenv("CORAL_ENABLE_LEG_TRACKING", "true").lower() in (
    "true",
    "1",
    "yes",
)
# Ceiling on leg mimicry, as a fraction of each leg joint's available
# travel from the stand pose. A LIMIT, not a scale: gentle leg
# movements pass through at full fidelity and only large ones are cut
# back.
#
# Measured against stepped dynamics (docs/cbf-whole-body-progress.md
# Phase 2.7), holding a maximum lift for 5s: 0.1 and 0.2 stay standing,
# 0.3 and above topple. 0.2 already rolls to -16 deg -- visibly
# struggling -- so the default sits below it.
#
# Raising this makes the lift more dramatic and less stable. 1.0
# disables the limit and will topple the robot on a full lift.
LEG_MIMICRY_MAX_TRAVEL = float(os.getenv("CORAL_LEG_MIMICRY_MAX_TRAVEL", "0.15"))

# ---------------------------------------------------------------------------
# Server binding
# ---------------------------------------------------------------------------
# Default to localhost for school/Electron deployments so the backend is not
# exposed on the classroom network. Docker/containerized runs should set
# CORAL_HOST=0.0.0.0 explicitly.
CORAL_HOST = os.getenv("CORAL_HOST", "127.0.0.1")
