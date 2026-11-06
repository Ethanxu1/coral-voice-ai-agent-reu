# CORAL Voice AI Agent

Multimodal AI dialogue agent for child-robot instruction grounding — Hiwonder AiNex humanoid robot.

## Overview

CORAL is a voice-driven demo that lets a child interact with the AiNex robot
through speech: the robot listens, works out what the child wants, and either
talks back (OpenAI TTS) or moves — copying a pose the child strikes, or
following a spoken instruction. Simulation (MuJoCo, shown in the browser) is
the default, so no robot is needed.

The laptop runs everything except the servos:

| Service | Where | Port |
|---------|-------|------|
| Frontend (React, served by nginx) | Docker | 5173 |
| Backend (FastAPI: LLM, Whisper, TTS, MuJoCo, motion safety) | Docker (host on Apple-chip Macs, see below) | 8000 |
| Postgres (saved poses) | Docker | 5432 |
| Vision server (webcam, MediaPipe) | Host — Docker on macOS can't reach a webcam | 8001 |

A Raspberry Pi on the robot (ROS Noetic, inside its `ainex` Docker container)
only drives the servos. See [docs/overview.md](docs/overview.md) for the
architecture and [docs/hardware.md](docs/hardware.md) for the physical robot.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Compose (Docker Desktop on macOS)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (Python 3.12+) — for the vision server
- An OpenAI API key

## Quick start

```bash
git clone <this repo> && cd coral-voice-ai-agent-reu
cp .env.example .env        # then set OPENAI_API_KEY
./run.sh
```

Open <http://localhost:5173> and click **✨ Start Demo Here**. The first run
builds the images and downloads the Whisper model, so it takes a few minutes.
Press Ctrl+C to stop everything.

```bash
./run.sh                            # simulation only
./run.sh -live                      # also drive the physical robot (ROBOT_IP from .env)
./run.sh -live -ip 192.168.8.219    # physical robot at an explicit IP
```

Logs go to `logs/stack.log` (containers) and `logs/vision.log`; each demo
session also writes a readable transcript under `logs/clean_logs/`.

On an Apple-chip Mac, `./run.sh` runs the backend on the host (`uv run server`,
logging to `logs/backend.log`) and keeps only Postgres and the frontend in
Docker. MediaPipe has no Linux-ARM build, so the backend image can't be built
natively there, and the Intel image under emulation gets MuJoCo's rotation
maths wrong (the simulated robot renders stretched).

On macOS the vision server opens the webcam from Python, so the camera
permission prompt comes from your terminal app. Grant it under System Settings
→ Privacy & Security → Camera, then rerun `./run.sh`.

## Development

```bash
uv sync                          # backend + vision dependencies
cd frontend && npm install       # frontend dependencies
```

- **Backend tests:** `docker compose up -d db && uv run python -m pytest`.
  Tests marked `db` are skipped when Postgres isn't running.
- **Lint:** `uv run ruff check backend`
- **Frontend:** `cd frontend && npm run dev` (hot reload on :5173 — stop the
  frontend container first) and `npm run build` (typecheck + build).
- **Motion check without the LLM or frontend:** `uv run sim-test [motion ...]`
  cycles the MuJoCo viewer through the canned motions in
  `backend/app/robot/motions.py`.
- **Manual harnesses** (collision sweep, leg buckets, motion playback,
  hardware command preview) live in `backend/tools/`:
  `uv run python backend/tools/<name>.py`.

Layout: `backend/app/` (the `app` package — `api/routes`, `services`, `llm`,
`robot`, `vision`, `collision`, `simulator`), `backend/tests/`,
`frontend/src/` (`pages`, `components`, `api`, `audio`, `demo`, `rps`),
`assets/ainex/` (robot model), `docs/`.

## Physical robot

The Pi side (wifi, starting the servo server, syncing code) is described in
[docs/hardware.md](docs/hardware.md). Check that the Pi's servo server is up
before `./run.sh -live`:

```bash
curl http://<robot ip>:9000/health
```

## Environment variables

Set these in `.env` (see `.env.example`).

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | Required: intent classification, motion planning, chat, TTS |
| `OPENAI_BASE_URL` | — | Point the OpenAI SDK at a compatible provider (read by the SDK) |
| `LLM_MODEL` | `gpt-5.4-mini` | Chat-completions model |
| `ROBOT_IP` | none (required for `-live`) | Physical robot's IP (hardware mode), e.g. `192.168.8.219` |
| `ROBOT_AGENT_PORT` | `9000` | Pi servo server port |
| `WHISPER_MODEL_SIZE` | `base` | faster-whisper size (`tiny`, `base`, `small`, and `.en` variants) |
| `TTS_ENABLED` | `auto` | `auto` speaks when an OpenAI key is set; `false` disables speech |
| `TTS_VOICE` / `TTS_MODEL` / `TTS_SPEED` | `coral` / `tts-1-hd` / `1.05` | OpenAI TTS settings |
| `INTENT_HIGH_CONFIDENCE_THRESHOLD` | `0.85` | Regex-matcher confidence needed to skip the LLM — see [intent-classifier.md](docs/intent-classifier.md) |
| `ENABLE_COLLISION_CHECK` | `true` | Self-collision clamp before every dispatch |
| `ENABLE_FALL_CHECK` | `true` | Fall/stability check before every dispatch |
| `FALL_HEAD_HEIGHT_FRAC` | `0.70` | Head-height fraction below which a pose counts as a fall |
| `CORAL_ENABLE_LEG_TRACKING` | `false` | Experimental leg retargeting in follow/capture |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` / `POSTGRES_PORT` | `coral` / `coral` / `coral` / `5432` | Compose database |
| `DATABASE_URL` | `postgresql://coral:coral@localhost:5432/coral` | Set automatically in Docker; used as-is by tests and native runs |
| `LANGFUSE_SECRET_KEY` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_BASE_URL` | — | Optional LLM tracing; unset disables it |
| `CORAL_MUJOCO_WINDOW` | `false` | Open the native MuJoCo window (native runs only, not in Docker) |
| `SIM_TEST_HOLD_SECONDS` | `2.0` | Seconds each motion is held in `uv run sim-test` |

The frontend reads `VITE_SERVER_BASE`, `VITE_ACTION_WS`, `VITE_SIM_WS`,
`VITE_VISION_BASE` and `VITE_ROBOT_HOST` at build time (`frontend/src/config.ts`);
the defaults match `./run.sh`.
