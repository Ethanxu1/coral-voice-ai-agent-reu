# CORAL Voice AI Agent

Multimodal AI Dialogue Agent for Child-Robot Instruction Grounding — Hiwonder AiNex humanoid robot.

## Overview

A voice-based AI agent that translates spoken natural-language instructions into physical robot motions. Supports two backends switchable with a single command:

| Mode | Command | What runs |
|------|---------|-----------|
| **Simulation** | `uv run server` | MuJoCo physics viewer (no robot required) |
| **Physical robot** | `uv run robot` | Commands sent to AiNex over the network |

Both modes share the same frontend, voice pipeline, and LLM motion planner. The laptop microphone and speakers are used in both modes.

## Architecture

### Simulation mode

```
Laptop
──────────────────────────────────────────────────────────────
Frontend (npm run dev, :5173)
  ↕ WebSocket
Server (uv run server, :8000)
  • Whisper — speech → text (laptop mic)
  • GPT-4o-mini — motion planning
  • SimController — MuJoCo joint interpolation
      ↓
  MuJoCo viewer window (AiNex 24-DOF model)
```

### Physical robot mode

```
Laptop                                Robot (192.168.8.219)
──────────────────────────────────    ──────────────────────────
Frontend (npm run dev, :5173)
  ↕ WebSocket
Server (uv run robot, :8000)      →   robot_agent.py (:9000)
  • Whisper (laptop mic/speakers)         • Raw Hiwonder LX serial
  • GPT-4o-mini — motion planning         • /dev/ttyAMA0 @ 115200
  • HardwareController                    • Safety clamps enforced
    ↳ per-joint angle conversion            (servo 20: 360–850)
    ↳ HTTP POST to robot agent
```

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Node.js 22+
- OpenAI API key
- Langfuse account (for LLM tracing)

### System libraries (Arch Linux)

```bash
sudo pacman -S --needed \
  portaudio libsndfile ffmpeg \
  alsa-lib libpulse \
  base-devel pkg-config cmake openssl \
  mesa glfw-x11 \
  libx11 libxi libxrandr libxcursor libxinerama \
  nodejs
```

## Setup

### 1. Install Python dependencies

```bash
uv sync
```

### 2. Download robot model (simulation only)

```bash
./scripts/download_assets.sh
```

### 3. Install frontend dependencies

```bash
cd frontend && npm install && cd ..
```

### 4. Configure environment

```bash
cp .env.example .env   # then fill in your keys
```

```
OPENAI_API_KEY=sk-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com
```

Get Langfuse keys at [cloud.langfuse.com](https://cloud.langfuse.com) → Settings → API Keys.

### 5. (Optional) SMPL shape calibration weights

Enables per-user body-shape calibration during the stable-pose capture, used to
normalize arm/leg segment lengths so the same pose maps to the same joint
angles across adults and children.

1. Register at <https://smpl.is.tue.mpg.de/> (academic use only).
2. Download the *SMPL_python_v.1.1.0* archive (or newer). Inside the archive
   the neutral weight file is `models/basicmodel_neutral_lbs_10_207_0_v1.1.0.pkl`.
3. Convert the legacy pickle to `.npz` using the bundled script (one-time, ~1 s).
   The pickle stores arrays as `chumpy.Ch`, which doesn't build under Python 3.12;
   the script stubs that out and saves clean numpy arrays:

   ```bash
   uv run python scripts/convert_smpl_pkl_to_npz.py \
     path/to/basicmodel_neutral_lbs_10_207_0_v1.1.0.pkl \
     assets/smpl/SMPL_NEUTRAL.npz
   ```

4. Install the optional torch/smplx stack:

   ```bash
   uv sync --extra smpl
   ```

If you skip this step the capture flow still works — shape calibration is just
silently disabled and a log message points you back here.

## Running

### Simulation mode

```bash
# Terminal 1
uv run server

# Terminal 2
cd frontend && npm run dev
```

Open <http://localhost:5173>.

### Physical robot mode

# ssh into the robot

```bash
# ssh into robot raspberry pi
ssh pi@192.168.8.219
```

**On the robot** (one-time setup):

```bash
pip install fastapi uvicorn pyserial
# copy robot_agent.py to the robot
scp src/coral_agent/robot/robot_agent.py ubuntu@192.168.8.219:~/robot_agent.py

# move robot_agent.py to docker container
docker cp /home/pi/robot_agent.py ainex:/home/ubuntu/ros_ws/src/<your_package>/robot_agent.py
```

**Every session:**

```bash

# ssh into robot raspberry pi
ssh pi@192.168.8.219
# open interactive terminal inside of docker container
docker exec -it ainex bash
# switch current terminal user to 'ubuntu'
su - ubuntu
cd /home/ubuntu

# run robot_agent.py
pyrun ~/ros_ws/src/robot_agent.py        # listens on :9000

# On the laptop (two terminals)
ROBOT_IP=192.168.8.219 uv run robot
cd frontend && npm run dev
```

Verify the robot agent is reachable before starting:

```bash
curl http://192.168.8.219:9000/health
# → {"status":"ok","backend":"_SerialBackend"}
```

If the serial port isn't `/dev/ttyAMA0`:

```bash
SERIAL_PORT=/dev/ttyUSB0 python3 ~/robot_agent.py
```

## Project Structure

```
coral-voice-ai-agent-reu/
├── src/coral_agent/
│   ├── server.py              # FastAPI server — sim and robot modes
│   ├── primitives.py          # Parameterized motion primitives
│   ├── validation.py          # Joint limit + sign validation
│   ├── state.py               # State checkpointing and rollback
│   ├── config.py              # LLM model selection
│   ├── prompts/
│   │   └── router.md          # Motion planner system prompt
│   ├── robot/
│   │   ├── interface.py           # RobotController abstract class
│   │   ├── sim_controller.py      # MuJoCo backend
│   │   ├── hardware_controller.py # Physical robot backend (laptop-side)
│   │   ├── hardware_angle_utils.py# Per-joint angle conversion
│   │   ├── robot_agent.py         # HTTP server to run ON the robot
│   │   ├── servo_config.py        # Servo ID map + STAND_PULSE values
│   │   └── angle_utils.py         # Sim-mode angle conversion
│   ├── simulator/
│   │   └── mujoco_sim.py          # AiNex MuJoCo wrapper (24 DOF)
│   └── vision/
│       └── vision_server.py       # MediaPipe pose server (:8001)
├── frontend/                  # Vite + React + TypeScript
│   └── src/
│       ├── App.tsx
│       └── components/
│           ├── ChatSidebar.tsx     # Voice/text chat + audio VAD
│           └── SimulatorControls.tsx
├── assets/                    # Robot models (downloaded, not in git)
├── recordings/                # Conversation logs (auto-generated)
├── scripts/
│   └── download_assets.sh
├── .env                       # API keys (not in git)
├── .env.robot                 # Robot mode env template
└── pyproject.toml
```

## Motion Primitives

The LLM uses these parameterized primitives. Each accepts an `angle` (degrees) and optional `speed` multiplier (0.1–8.0, default 1.0):

| Primitive | Description | Max Angle | Direction |
|-----------|-------------|-----------|-----------|
| `left_arm_out` | Left arm sideways abduction | 119° | — |
| `right_arm_out` | Right arm sideways abduction | 119° | — |
| `left_arm_forward` | Left arm forward/up flexion | 119° | — |
| `right_arm_forward` | Right arm forward/up flexion | 119° | — |
| `left_elbow_bend` | Bend left elbow | 119° | — |
| `right_elbow_bend` | Bend right elbow | 119° | — |
| `left_elbow_rotate` | Rotate left forearm | 119° | in / out |
| `right_elbow_rotate` | Rotate right forearm | 119° | in / out |
| `head_turn` | Turn head | 119° | left / right |
| `head_tilt` | Tilt head | 119° | up / down |
| `neutral` | Reset all arm + head joints to stand | — | — |

Example chat commands:

- *"Raise your right arm to 90 degrees"*
- *"Turn your head left while waving"*
- *"Bend your left elbow halfway"*

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
| l_el_pitch / r_el_pitch | 17 / 18 | 500 / 500 | forearm rotation |
| l_el_yaw | 19 | 150 | safe range 0–600 |
| r_el_yaw | 20 | 850 | **DAMAGED — clamped to 360–850** |
| l_gripper / r_gripper | 21 / 22 | 500 / 500 | |
| head_pan / head_tilt | 23 / 24 | 500 / 500 | not physically present |

## Robot Agent API

Endpoints served by `robot_agent.py` on the robot at `:9000`:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Returns `{"status":"ok","backend":"..."}` |
| POST | `/move` | Move servos: `[{"servo_id":13,"position":460,"duration_ms":1000},...]` |
| POST | `/stand` | Return all servos to standing pose |
| POST | `/feedback` | Read servo positions/temps: `{"servo_ids":[13,14]}` |
| GET | `/positions` | Current position of all 24 servos |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ROBOT_MODE` | `sim` | `sim` = MuJoCo, `robot` = physical robot |
| `ROBOT_IP` | `192.168.8.219` | Robot's IP on your network |
| `ROBOT_AGENT_PORT` | `9000` | Port the robot agent listens on |
| `SERIAL_PORT` | `/dev/ttyAMA0` | Serial port on the robot for servo bus |
| `AGENT_PORT` | `9000` | Same as above, set on the robot side |

## License

See individual component licenses:

- AiNex MuJoCo model: see `assets/ainex/`
