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

Copy the ROS package into the catkin workspace:

```bash
cp -r /path/to/repo/src/robot/pi/ ~/ros_ws/src/ainex_demo/
chmod +x ~/ros_ws/src/ainex_demo/nodes/*.py
```

Build the package:

```bash
cd ~/ros_ws
catkin build ainex_demo
source devel/setup.bash
```

Nothing else to do here for the pose classifier — it doesn't run on the Pi. The
MobileNetV3 checkpoint ships pretrained in this repo at
`src/vision/models/pose_classifier.pt` and is loaded automatically by the Mac's
vision server (`CLASSIFIER_PATH` below overrides the path). Running inference
needs torch + torchvision on the Mac (`uv sync --extra robot`); without it the
vision server still runs, but `/classify` errors until you install that extra.

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

### Laptop (four terminals)

All four are required — the demo pages wait on the vision and speaker
servers, so a missing one looks like the demo hanging rather than a clean
error.

```bash
# Terminal 1 — voice + LLM server + MuJoCo simulator          (:8000)
uv run server                          # simulation mode
# or
ROBOT_IP=192.168.8.219 uv run robot    # physical robot mode (no MuJoCo)

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
cd ~/ros_ws && source devel/setup.bash
roslaunch ainex_demo ainex_demo.launch
```

Verify the Pi's server node (`nodes/server.py`) is up:

```bash
curl http://192.168.8.219:9000/health
```

### Syncing files to Pi

[`utils/dump.sh`](utils/dump.sh) pushes a file from Mac → Pi → Docker container in one command. Install it on your `PATH` first (see [hardware.md](docs/hardware.md) for the one-time setup, including editing its hard-coded `REPO_ROOT`):

```bash
dump src/robot/pi/nodes/server.py
# then when prompted: Write to: /home/ubuntu/ros_ws/src/____
#   type: ainex_demo/nodes
```

Full behavior (path flattening, `sshpass` requirement, troubleshooting) is in [hardware.md](docs/hardware.md).

Files in `nodes/` take effect immediately (no rebuild). Changes to `CMakeLists.txt`, `package.xml`, or `srv/` require `catkin build ainex_demo`.

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
