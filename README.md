# CORAL Voice AI Agent

Multimodal AI Dialogue Agent for Child-Robot Instruction Grounding

## Overview

This project provides a voice-based AI agent that helps translate spoken instructions into executable robot commands. It includes:

- **MuJoCo Simulator**: Apptronik Apollo humanoid robot with independent head and torso control
- **FastAPI Backend**: WebSocket server with OpenAI GPT-4o-mini and Langfuse tracing for natural language understanding
- **React Frontend**: Control panel with manual robot controls and chat interface

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (Vite + React)                 │
│  ┌─────────────────────────────┐ ┌───────────────────────────┐  │
│  │      Control Panel          │ │      Chat Sidebar         │  │
│  │  - Head controls            │ │  - Message history        │  │
│  │  - Torso controls           │ │  - User input             │  │
│  │  - Arm controls             │ │  - Command highlighting   │  │
│  │  - Preset poses             │ │                           │  │
│  └─────────────────────────────┘ └───────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │ WebSocket
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Backend (FastAPI + Python)                   │
│  - /ws - WebSocket for chat + commands                         │
│  - Intent classifier (fast-path + LLM fallback)                │
│  - OpenAI GPT-4o-mini via Langfuse tracing                     │
│  - Parameterized motion primitives                             │
│  - MuJoCo simulator control                                    │
└─────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│              MuJoCo Viewer (Separate Window)                    │
│                  Apptronik Apollo Humanoid                      │
└─────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Node.js 22+
- OpenAI API key (for GPT-4o-mini)
- Langfuse account (for LLM tracing/observability)
- System libraries (see step 1 below)

## Setup

### 1. Install system dependencies

**Arch Linux:**

```bash
sudo pacman -S --needed \
  portaudio libsndfile ffmpeg \
  alsa-lib libpulse \
  base-devel pkg-config cmake openssl \
  mesa glfw-x11 \
  libx11 libxi libxrandr libxcursor libxinerama \
  nodejs
```

### 2. Install Python dependencies

```bash
uv sync
```

### 3. Download robot model assets

The robot models are not included in the repository. Run the provided script to download the Apptronik Apollo model from MuJoCo Menagerie:

```bash
./scripts/download_assets.sh
```

### 4. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### 5. Configure environment variables

Copy the example environment file and fill in your API keys:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```
OPENAI_API_KEY=your_openai_api_key_here
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com
```

Get your Langfuse keys at [cloud.langfuse.com](https://cloud.langfuse.com) under Settings > API Keys.

## Running the Application

### Start the backend server

```bash
uv run server
```

This will:
- Start the FastAPI server on http://localhost:8000
- Open a MuJoCo viewer window showing the Apollo robot

### Start the frontend (in a separate terminal)

```bash
cd frontend
npm run dev
```

Open http://localhost:5173 in your browser.

## Usage

### Manual Controls

Use the control panel buttons to move the robot:

- **Head**: Turn left/right, look up/down (independent from torso)
- **Torso**: Rotate left/right, lean forward/backward/left/right
- **Arms**: Up/down/in/out, bend/extend elbow
- **Presets**: Wave, point, nod yes, shake no, reset

### Chat Interface

Type natural language commands in the chat:

- "Wave at me"
- "Turn your head to the left"
- "Raise your right arm"
- "Nod yes"

The LLM will interpret your request and execute the appropriate robot commands.

## Project Structure

```
coral-voice-ai-agent-reu/
├── src/coral_agent/
│   ├── server.py                 # FastAPI backend + motion planning
│   ├── intent.py                 # Stage 1: Intent classifier
│   ├── primitives.py             # Parameterized motion primitives
│   ├── validation.py             # Joint limit + sign validation
│   ├── state.py                  # State checkpointing and rollback
│   ├── schemas.py                # Pydantic models for LLM output
│   ├── gesture_library.py        # Animated social gestures
│   ├── bot.py                    # Voice agent (pipecat)
│   ├── test_local.py             # Local dialogue testing
│   ├── test_langfuse.py          # Langfuse tracing tests
│   ├── prompts/
│   │   ├── router.md             # Router agent system prompt
│   │   └── intent.md             # Intent classifier prompt
│   └── simulator/
│       ├── __init__.py
│       └── mujoco_sim.py         # MuJoCo Apollo wrapper
├── assets/                        # Robot models (not in git)
│   └── apptronik_apollo/         # Downloaded from mujoco_menagerie
├── frontend/                      # Vite + React + TypeScript
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── ChatSidebar.tsx
│   │   │   └── SimulatorControls.tsx
│   │   └── ...
│   └── ...
├── recordings/                    # Conversation logs (auto-generated)
├── scripts/
│   └── download_assets.sh        # Downloads robot model assets
├── pyproject.toml                # Python dependencies
└── README.md
```

## Available Motion Primitives

The LLM chat interface uses parameterized primitives — each accepts an angle (in degrees) and optional direction/speed:

| Primitive | Description | Max Angle | Direction |
|-----------|-------------|-----------|-----------|
| `left_arm_out` | Left arm sideways (abduction) | 160° | — |
| `right_arm_out` | Right arm sideways (abduction) | 160° | — |
| `left_arm_forward` | Left arm forward/up (flexion) | 125° | — |
| `right_arm_forward` | Right arm forward/up (flexion) | 125° | — |
| `left_elbow_bend` | Bend left elbow | 150° | — |
| `right_elbow_bend` | Bend right elbow | 150° | — |
| `head_turn` | Turn head | 95° | left / right |
| `head_tilt` | Tilt head | 30° | up / down |
| `torso_rotate` | Rotate torso | 47° | left / right |
| `torso_lean` | Lean torso forward | 77° | — |
| `neutral` | Reset all joints to zero | — | — |

### Manual Control Commands (via `/command` API)

| Category | Commands |
|----------|----------|
| Head | `head_left`, `head_right`, `head_up`, `head_down` |
| Torso | `torso_left`, `torso_right`, `lean_forward`, `lean_backward`, `lean_left`, `lean_right` |
| Left Arm | `left_arm_up`, `left_arm_down`, `left_arm_out`, `left_arm_in`, `left_elbow_bend`, `left_elbow_extend` |
| Right Arm | `right_arm_up`, `right_arm_down`, `right_arm_out`, `right_arm_in`, `right_elbow_bend`, `right_elbow_extend` |
| Gestures | `wave`, `point`, `nod`, `shake`, `look_around`, `reset` |

## License

See individual component licenses:
- Apptronik Apollo model: Apache-2.0 (from MuJoCo Menagerie)
