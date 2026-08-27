# CORAL Voice AI Agent

Multimodal AI dialogue agent for child-robot instruction grounding — Hiwonder AiNex humanoid robot.

## Overview

CORAL is a voice-driven demo system that lets a child interact with the AiNex robot through speech. 

The Mac runs the frontend, LLM server, vision, and TTS. The Pi (inside an `ainex` Docker container with ROS Noetic) controls the physical robot servos.


## Prerequisites

**Laptop**

- Python 3.12+ and [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Node.js 22+
- OpenAI API key

**Pi**

- ROS Noetic inside the `ainex` Docker container
- `catkin_tools` (`pip install catkin-tools`)

The pose classifier now runs on the Mac (via the vision server), not on the Pi — the Pi side has no PyTorch dependency. See the note under "Pi Setup" below.

## Mac Setup

### 1. Install Python dependencies

```bash
uv sync
```

### 2. Install frontend dependencies

```bash
cd frontend && npm install && cd ..
```

### 3. Configure environment

```bash
cp .env.example .env
```

Fill in your keys:

```
OPENAI_API_KEY=sk-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com
```

Only `OPENAI_API_KEY` is required. Leave the Langfuse keys blank and tracing disables itself.

## Pi Setup (one-time)

SSH into the Pi and open the Docker container:

```bash
ssh pi@raspberrypi.local
docker exec -it ainex bash
su - ubuntu
```

## Running

### Laptop (four terminals)

All four are required — the demo pages wait on the vision and speaker
servers, so a missing one looks like the demo hanging rather than a clean
error.

```bash
# Terminal 1 — voice + LLM server + MuJoCo simulator          (:8000)
uv run server                          # simulation mode
# or
ROBOT_IP={robot ip addr} && uv run robot    # physical robot mode (no MuJoCo)

# Terminal 2 — vision server: webcam → body pose              (:8001)
uv run vision

# Terminal 3 — speaker server: text-to-speech for the demo    (:5002)
uv run speaker

# Terminal 4 — frontend                                       (:5173)
cd frontend && npm run dev
```

Open <http://localhost:5173> and click **✨ Start Demo Here**.

On macOS, `uv run vision` opens the webcam from Python, so the camera permission prompt comes from your terminal app. Grant it under System Settings → Privacy & Security → Camera, then restart the vision server.

To cycle the simulator through every motion in `motions.py` without the LLM or frontend:

```bash
uv run sim-test              # all motions
uv run sim-test dab wave     # only these
```

### Pi (every session)

```bash
ssh pi@raspberrypi.local
docker exec -it ainex bash
su - ubuntu
cd ~/ros_ws/src
pyrun vision/robot_agent.py
```

Verify the Pi's server node (`nodes/server.py`) is up:

```bash
curl http://192.168.8.219:9000/health
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | Required for LLM motion planner |
| `OPENAI_BASE_URL` | — | Points the OpenAI SDK at a compatible provider (e.g. DeepSeek); read by the SDK itself, not app code |
| `ROBOT_MODE` | `sim` | `sim` or `robot`; set automatically by `uv run server` / `uv run robot`, or override directly |
| `ROBOT_IP` | `192.168.8.219` | Robot's IP on your network (hardware mode only) |
| `ROBOT_AGENT_PORT` | `9000` | Pi server port, as dialed by the Mac |
| `AGENT_PORT` | `9000` | Port the Pi server binds to (Pi side) |
| `SPEAKER_PORT` | `5002` | TTS speaker server port |
| `SAY_RATE` | `220` | Speaker server's speech rate (words per minute) |
| `VISION_BASE` | `http://localhost:8001` | Vision server URL, as dialed by the main server |
| `CLASSIFIER_PATH` | `src/vision/models/pose_classifier.pt` | MobileNetV3 checkpoint, loaded by the Mac vision server |
| `WHISPER_MODEL_SIZE` | `base` | faster-whisper model size (`tiny`, `base`, `small`, and `.en` variants) |
| `INTENT_HIGH_CONFIDENCE_THRESHOLD` | `0.85` | Minimum regex-matcher confidence before skipping the LLM fallback — see [intent-classifier.md](docs/intent-classifier.md) |
| `ENABLE_COLLISION_CHECK` | `true` | Set `false` to disable the self-collision clamp before dispatch |
| `ENABLE_FALL_CHECK` | `true` | Set `false` to disable the fall/stability check before dispatch |
| `FALL_HEAD_HEIGHT_FRAC` | `0.70` | Stability checker's minimum head-height fraction before a pose is considered a fall |
| `SIM_TEST_HOLD_SECONDS` | `2.0` | Seconds to hold each motion in `uv run sim-test` |
| `LANGFUSE_SECRET_KEY` / `LANGFUSE_PUBLIC_KEY` | — | LLM tracing (optional); unset disables tracing entirely, no error |
| `LANGFUSE_BASE_URL` | `https://cloud.langfuse.com` (SDK default) | Langfuse endpoint; `.env.example` ships the US region (`https://us.cloud.langfuse.com`) |
| `CORAL_NO_VIEWER` | — | Set `1` to keep the MuJoCo run on plain `python` on macOS instead of re-exec'ing under `mjpython` to open the viewer window (headless/CI runs) |
