# CORAL Voice AI Agent

Multimodal AI dialogue agent for child-robot instruction grounding — Hiwonder AiNex humanoid robot.

## Overview

CORAL is a voice-driven demo system that lets a child interact with the AiNex robot through speech. It has two main modes:

- **Director demo** — a guided INTRO → CLASSIFY → RECORD → OUTRO pipeline where the robot poses, classifies the child's pose via camera, and takes voice corrections
- **Testing mode** — open-ended voice → motion control via Whisper + GPT-4o-mini

The Mac runs the frontend, LLM server, and TTS. The Pi (inside an `ainex` Docker container with ROS Noetic) controls the physical robot servos.

## Prerequisites

**Laptop**

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

Fill in your keys:

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

### (Optional) SMPL shape calibration weights

Enables per-user body-shape calibration during pose capture, normalizing arm/leg segment lengths so the same pose maps to the same joint angles across adults and children.

1. Register at <https://smpl.is.tue.mpg.de/> (academic use only).
2. Download the *SMPL_python_v.1.1.0* archive. The neutral weight file is `models/basicmodel_neutral_lbs_10_207_0_v1.1.0.pkl`.
3. Convert the legacy pickle to `.npz` (one-time, ~1 s):

   ```bash
   uv run python scripts/convert_smpl_pkl_to_npz.py \
     path/to/basicmodel_neutral_lbs_10_207_0_v1.1.0.pkl \
     assets/smpl/SMPL_NEUTRAL.npz
   ```

4. Install the optional torch/smplx stack:

   ```bash
   uv sync --extra smpl
   ```

If you skip this step the capture flow still works — shape calibration is silently disabled and a log message points you back here.

## Running

### Laptop (three terminals)

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

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | Required for LLM motion planner |
| `ROBOT_IP` | `192.168.8.219` | Robot's IP on your network |
| `ROBOT_AGENT_PORT` | `9000` | robot_server port |
| `AGENT_PORT` | `9000` | Port robot_server binds to (Pi side) |
| `CLASSIFIER_PATH` | `model/pose_classifier.pt` | Path to MobileNetV3 checkpoint |
| `LANGFUSE_SECRET_KEY` / `LANGFUSE_PUBLIC_KEY` | — | LLM tracing (optional) |
| `LANGFUSE_BASE_URL` | `https://us.cloud.langfuse.com` | Langfuse endpoint |
