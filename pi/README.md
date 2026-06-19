# Pi side — `coral_demo` ROS package

Robot-side ROS1 nodes for the CORAL pose-learning demo. These run **on the AiNex
Raspberry Pi** (inside the `ainex` docker container, as the original demo did).
The Mac-side director / audio / speaker and the browser frontend talk to these
nodes over **rosbridge**.

## Nodes

| Node | Type | Publishes / Services |
|------|------|----------------------|
| `vision_node.py` | camera + MediaPipe + classifier | pub `/stable_gest/landmarks`, `/stable_gest/image_annotated`, `/stable_gest/image_clean`; srv `~classify_frame`, `~watch_gesture` |
| `head_node.py` | subject tracking | subs `/stable_gest/landmarks`, drives head pan/tilt |
| `body_node.py` | pose actuation | srv `~execute_body` (blocking until motion done) |

All nodes subscribe to `/system/shutdown` (latched `Bool`) for a coordinated stop.

## Services (`srv/`)

- `ClassifyFrame` — classify the most-stable recent clean frame → `move`, `confidence`, `had_human`, `jpeg`
- `WatchForGesture` — block until the subject does a gesture (`hands_close`) or `timeout`
- `ExecuteBody` — move body servos, **block** until `duration_ms` elapsed; pose-class or explicit servo targets

## Dependencies (on the Pi)

Provided by the AiNex image: `ros` (Noetic), `ainex_kinematics`, `ainex_sdk`,
the camera node. Install the rest into the container:

```bash
pip install mediapipe torch torchvision opencv-python pillow numpy
sudo apt install ros-noetic-rosbridge-server   # or build from source
```

## Build & run

```bash
cd pi/catkin_ws
catkin_make            # generates the ClassifyFrame/WatchForGesture/ExecuteBody msgs
source devel/setup.bash

# start the AiNex camera node first (provides /camera + image topic), then:
roslaunch coral_demo coral_demo.launch dev_mode:=true
```

`dev_mode:=true` forces body pose-class moves to the stand pose (per the demo
spec); set `false` once the real poses are validated on hardware.

## Dev-mode notes / TODO before going live

- `body_node` ignores the classified pose class in dev mode and just stands.
  Flip `dev_mode:=false` to execute the real `*_PULSE` poses from `poses.py`.
- The classifier class labels in `poses.py:CLASS_TO_PULSE` must match
  `checkpoint['classes']` in `model/pose_classifier.pt`.
