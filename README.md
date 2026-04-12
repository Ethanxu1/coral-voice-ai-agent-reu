# CORAL Voice AI Agent

Multimodal AI Dialogue Agent for Child-Robot Instruction Grounding

## Overview

This project provides a voice-based AI agent that helps translate spoken instructions into executable robot commands. It includes:

- **MuJoCo Simulator**: Apptronik Apollo humanoid robot with independent head and torso control
- **FastAPI Backend**: WebSocket server with Ollama LLM integration for natural language understanding
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
│  - Ollama LLM integration                                      │
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
- [Ollama](https://ollama.ai/) for LLM inference
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

### 5. Set up Ollama

Make sure Ollama is running and pull the required model:

```bash
ollama serve  # Start Ollama (if not already running)
ollama pull llama3.2
```

### 6. Configure environment variables

Copy the example environment file and edit as needed:

```bash
cp .env.example .env
```

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
│   ├── bot.py                    # Voice agent (pipecat)
│   ├── server.py                 # FastAPI backend
│   ├── test_local.py             # Local LLM testing
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
├── scripts/
│   └── download_assets.sh        # Downloads robot model assets
├── pyproject.toml                # Python dependencies
└── README.md
```

## Available Commands

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
