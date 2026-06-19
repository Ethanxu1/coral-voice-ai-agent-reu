# CORAL — Pose-Learning Robot Demo

An interactive demo where the AiNex humanoid ("Robert") asks a child to strike a
pose, photographs and **classifies** it, mimics it, then asks the child to
**verbally correct** its pose. Built as a distributed ROS system split across the
robot's Pi and a Mac, connected by **rosbridge**.

## Architecture

```
Pi (ROS1 + rosbridge_server :9090)         Mac (roslibpy clients)
─────────────────────────────────         ────────────────────────────
vision_node   camera + MediaPipe           director_node  state machine
              + pose classifier            audio_node     Whisper + LLM
              srv: classify_frame,         speaker_node   espeak (TTS)
                   watch_gesture
head_node     subject tracking                    │
body_node     servo control                       │ rosbridge WebSocket
              srv: execute_body  ◄────────────────┘
                                           Browser (React + roslibjs)
                                             demo UI, mic capture
```

- **Pi** runs the real `rospy` nodes (camera, MediaPipe, classifier, servos) — it
  can't move off the robot. See [pi/README.md](pi/README.md).
- **Mac** can't run ROS1, so `director` / `audio` / `speaker` are **roslibpy
  clients** that connect to the Pi's `rosbridge_server` and behave like ROS nodes.
- **Frontend** (React + roslibjs) connects to the same rosbridge.

## Demo flow

`INTRO → (LOOP_START → RECORD) × N → OUTRO`, orchestrated by `director_node`. Each
step is a **blocking** service call so the demo only advances when the previous
action (speech, classification, motion) has actually finished.

1. **Intro** — Robert greets, waves, asks for a pose; advances when the child
   crosses their hands (`vision/watch_gesture`).
2. **Loop start** — countdown, camera click, `vision/classify_frame` → pose class,
   `body/execute_body` mimics it (dev mode: returns to stand).
3. **Record** — child says how to fix the pose; the browser records, calls
   `audio/audio_to_action` (Whisper + LLM → safe servo targets), and Robert adjusts.
4. **Outro** — Robert explains the ML in simple terms.

`DEMO_LOOP_REPEATS` controls N (default 2).

## Running

### 1. On the Pi
```bash
cd pi/catkin_ws && catkin_make && source devel/setup.bash
# start the AiNex camera node, then:
roslaunch coral_demo coral_demo.launch dev_mode:=true
```

### 2. On the Mac
```bash
uv sync
cp .env.example .env          # set OPENAI_API_KEY
brew install espeak           # TTS
export ROS_HOST=<pi-ip>       # rosbridge host (default 192.168.8.219)

uv run speaker &
uv run audio &
uv run director               # starts the demo
```

### 3. Frontend
```bash
cd frontend && npm install
cp .env.example .env          # set VITE_ROS_HOST=<pi-ip>
npm run dev                   # http://localhost:5173
```

## Layout

```
pi/catkin_ws/src/coral_demo/   ROS1 package (vision/head/body nodes, srv/, model/, poses.py)
mac/coral_agent/               roslibpy nodes (director/audio/speaker) + reused motion planner
frontend/                      React + roslibjs demo UI
```

## Environment variables

| Variable | Default | Where | Description |
|----------|---------|-------|-------------|
| `OPENAI_API_KEY` | — | Mac | required for the voice motion planner |
| `OPENAI_BASE_URL` | OpenAI | Mac | override for OpenAI-compatible APIs |
| `ROS_HOST` | `192.168.8.219` | Mac | Pi IP running rosbridge |
| `ROS_BRIDGE_PORT` | `9090` | Mac | rosbridge port |
| `DEMO_LOOP_REPEATS` | `2` | Mac | how many learn-a-move loops |
| `VITE_ROS_HOST` | `localhost` | frontend | Pi IP for the browser |

## Skeleton status

This is the **skeleton + stubs** pass. Known TODOs before a live run:
- `body_node` dev mode forces pose-class moves to stand — flip `dev_mode:=false`
  to execute the real `*_PULSE` poses once validated on hardware.
- `audio_node` flattens multi-step / parallel motion plans into one pose.
- Wave / thumbs-up flourishes and polished UI animations are placeholders.
