# CORAL Voice AI Agent

Multimodal AI dialogue agent for child-robot instruction grounding — Hiwonder AiNex humanoid robot.

## Overview

CORAL is a voice-driven demo system that lets a child interact with the AiNex robot through speech. It has two main modes:

- **Director demo** — a guided INTRO → CLASSIFY → RECORD → OUTRO pipeline where the robot poses, classifies the child's pose via camera, and takes voice corrections
- **Testing mode** — open-ended voice → motion control via Whisper + GPT-4o-mini

## Architecture

```
Mac
──────────────────────────────────────────────────────────
Frontend       (npm run dev, :5173)   React + Vite UI
Server         (uv run server, :8000) Whisper + LLM motion planner
Speaker server (uv run speaker, :5002) pyttsx3 TTS (blocking)

Pi (inside ainex Docker container)
──────────────────────────────────────────────────────────
robot_server.py (:9000)  FastAPI — /motion /classify /watch-for-action /state /move /stand
vision.py       (ROS)    Camera → MediaPipe → /annotated_frame /clean_frame /landmarks
head.py         (ROS)    Shoulder-midpoint tracking → head pan/tilt servos
body.py         (ROS)    /body-commands service — executes motion sequences blocking
MJPEG stream    (:9001)  /video_feed (annotated) /clean_feed (raw) for frontend
```

## Prerequisites

**Mac**
- Python 3.12+ and [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Node.js 22+
- OpenAI API key

**Pi**
- ROS Noetic inside the `ainex` Docker container
- `catkin_tools` (`pip install catkin-tools`)
- PyTorch + torchvision (for pose classifier in robot_server)

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

```
OPENAI_API_KEY=sk-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com
```

## Pi Setup (one-time)

SSH into the Pi and open the Docker container:

```bash
ssh pi@raspberrypi.local
docker exec -it ainex bash
su - ubuntu
```

Copy the ROS package into the catkin workspace:

```bash
cp -r /path/to/ros/ ~/ros_ws/src/ainex_demo/
chmod +x ~/ros_ws/src/ainex_demo/nodes/*.py
```

Build the package:

```bash
cd ~/ros_ws
catkin build ainex_demo
source devel/setup.bash
```

Place the pose classifier checkpoint at:

```
~/ros_ws/src/ainex_demo/nodes/model/pose_classifier.pt
```

## Running

### Mac (three terminals)

```bash
# Terminal 1 — voice + LLM server
uv run server          # simulation mode
# or
ROBOT_IP=192.168.8.219 uv run robot   # physical robot mode

# Terminal 2 — TTS speaker
uv run speaker

# Terminal 3 — frontend
cd frontend && npm run dev
```

Open <http://localhost:5173>.

### Pi (every session)

```bash
ssh pi@raspberrypi.local
docker exec -it ainex bash
su - ubuntu
cd ~/ros_ws && source devel/setup.bash
roslaunch ainex_demo ainex_demo.launch
```

Verify robot_server is up:

```bash
curl http://192.168.8.219:9000/health
```

### Syncing files to Pi

Use the `dump` command to push a file from Mac → Pi → Docker container:

```bash
dump src/coral_agent/robot/ros/nodes/robot_server.py
dump src/coral_agent/robot/ros/nodes/motions.py
```

Files in `nodes/` take effect immediately (no rebuild). Changes to `CMakeLists.txt`, `package.xml`, or `srv/` require `catkin build ainex_demo`.

## Project Structure

```
coral-voice-ai-agent-reu/
├── src/coral_agent/
│   ├── server.py                  # FastAPI — Whisper + LLM motion planner (:8000)
│   ├── config.py                  # LLM model + env config
│   ├── primitives.py              # Parameterized motion primitives (sim mode)
│   ├── prompts/
│   │   └── router.md              # LLM system prompt
│   ├── speaker/
│   │   ├── speaker_server.py      # pyttsx3 TTS server (:5002)
│   │   └── scripts.py             # Kid-friendly speech lines
│   ├── robot/
│   │   ├── motions.py             # Pose pulse dicts + named motion sequences (Mac copy)
│   │   ├── hardware_controller.py # Laptop-side HTTP client → robot_server
│   │   ├── interface.py           # RobotController abstract class
│   │   ├── sim_controller.py      # MuJoCo backend
│   │   └── ros/                   # catkin package (ainex_demo) — runs on Pi
│   │       ├── CMakeLists.txt
│   │       ├── package.xml
│   │       ├── ainex_demo.launch
│   │       ├── srv/
│   │       │   └── BodyCommand.srv
│   │       └── nodes/
│   │           ├── robot_server.py  # FastAPI HTTP bridge (:9000)
│   │           ├── vision.py        # Camera + MediaPipe + MJPEG (:9001)
│   │           ├── head.py          # Head tracking node
│   │           ├── body.py          # /body-commands ROS service
│   │           └── motions.py       # Pose pulse dicts + named motions (Pi copy)
│   └── vision/
│       └── vision_server.py       # Mac-side MediaPipe server (legacy)
├── frontend/
│   └── src/
│       ├── App.tsx
│       ├── pages/
│       │   └── DemoPage.tsx       # Director demo UI
│       ├── demo/
│       │   ├── useDemoMachine.ts  # useReducer state machine
│       │   ├── api.ts             # speak / motion / classify / watchForAction helpers
│       │   └── components.tsx     # Countdown, CameraFlash, ClassifyCard, etc.
│       └── components/
│           └── pose/              # Testing mode components
├── pose_settings.py               # (legacy — merged into motions.py)
├── .env                           # API keys (not in git)
└── pyproject.toml
```

## robot_server API (:9000)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Status + current robot state + classifier classes |
| GET | `/state` | Current robot state (`IDLE`, `MOTION`, etc.) |
| POST | `/state` | Set robot state — demo uses this to lock/unlock |
| POST | `/motion` | Run a named motion: `{"name": "wave"}` |
| POST | `/classify` | Classify current camera frame → class + probabilities + image |
| GET | `/watch-for-action` | Block until hands-close gesture (default 30s timeout) |
| POST | `/move` | Legacy servo move — 429 when robot is locked |
| POST | `/stand` | Return to standing pose |
| POST | `/feedback` | Servo feedback (compat) |
| GET | `/positions` | All 24 servo positions (compat) |

### Named motions (`/motion`)

`wave`, `stand`, `t-pose`, `dab`, `superhero`, `thinker`, `muscles`, `hand-raised`, `warrior2`

### Robot states

| State | Meaning |
|-------|---------|
| `IDLE` | Ready for any command |
| `MOTION` | Executing a motion sequence |
| `CLASSIFYING` | Capturing + classifying a frame |
| `WATCHING` | Waiting for hands-close gesture |
| `DEMO_LOCKED` | Demo owns the robot — `/move` returns 429 |

## Speaker API (:5002)

```bash
POST /speak   {"script": "INTRO"}    # speak a named script
POST /speak   {"text": "Hello!"}     # speak arbitrary text (blocks until done)
GET  /scripts                        # list available script names
GET  /health
```

## Servo Map (AiNex 24 DOF)

| Joint | Servo ID | Stand pulse | Notes |
|-------|----------|-------------|-------|
| l_ank_roll / r_ank_roll | 1 / 2 | 500 / 500 | |
| l_ank_pitch / r_ank_pitch | 3 / 4 | 640 / 360 | |
| l_knee / r_knee | 5 / 6 | 500 / 500 | |
| l_hip_pitch / r_hip_pitch | 7 / 8 | 350 / 650 | |
| l_hip_roll / r_hip_roll | 9 / 10 | 500 / 500 | |
| l_hip_yaw / r_hip_yaw | 11 / 12 | 500 / 500 | |
| l_sho_pitch / r_sho_pitch | 13 / 14 | 835 / 165 | |
| l_sho_roll / r_sho_roll | 15 / 16 | 830 / 170 | |
| l_el_pitch / r_el_pitch | 17 / 18 | 500 / 500 | |
| l_el_yaw | 19 | 150 | safe range 0–600 |
| r_el_yaw | 20 | 850 | **DAMAGED — clamped to 360–850** |
| l_gripper / r_gripper | 21 / 22 | 500 / 500 | |
| head_pan / head_tilt | 23 / 24 | 500 / 500 | |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ROBOT_IP` | `192.168.8.219` | Robot's IP on your network |
| `ROBOT_AGENT_PORT` | `9000` | robot_server port |
| `AGENT_PORT` | `9000` | Port robot_server binds to (Pi side) |
| `CLASSIFIER_PATH` | `model/pose_classifier.pt` | Path to MobileNetV3 checkpoint |
| `OPENAI_API_KEY` | — | Required for LLM motion planner |
