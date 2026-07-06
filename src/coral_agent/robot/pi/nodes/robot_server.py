#!/usr/bin/env python3
"""Robot server (Pi side) — the single HTTP interface between the Mac and the Pi.

Consolidates the old ``robot_agent.py`` HTTP surface and adds the Director-demo
endpoints. Runs as a rospy node *and* a FastAPI server so it can both call the
ROS ``/body_commands`` service and read the vision topics (``/clean_frame``,
``/landmarks``) while exposing plain REST to the laptop frontend.

Endpoints
    POST /motion            run a named motion (blocks until the body finishes)
    POST /classify          classify the current frame (MobileNetV3) → class + image
    GET  /watch-for-action  block until "hands close" gesture (30s timeout)
    POST /state             set the global robot_state (demo lock / unlock)
    GET  /state             read the global robot_state
    POST /move              legacy servo move (voice pipeline) — 429 when locked
    POST /stand             return to stand pose
    GET  /health /positions /feedback   status/compat

Concurrency: a single module-global ``_robot_state`` records what the robot is
doing. Conflicting motor commands return 429 Conflict — no hardware locks needed.

Run inside the robot's ROS environment:
    source /home/ubuntu/ros_ws/devel/setup.bash
    python3 robot_server.py

Environment variables:
    AGENT_PORT      HTTP port (default: 9000)
    CLASSIFIER_PATH path to the MobileNetV3 checkpoint (default: model/pose_classifier.pt)
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from enum import Enum
from typing import Dict, List, Optional, Tuple

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# catkin's devel-space "install" for Python scripts isn't a real symlink — it's
# a relay stub that execs the true source file into a throwaway local dict, so
# top-level defs never land on the actual module object (a plain `import X`
# then finds that broken stub instead of the real file, and `from X import
# name` fails with "cannot import name"). __file__ still points at this file's
# real source path even under that stub, so use it to force local imports
# (motions, pose_to_robot) to resolve from the true source directory instead.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import motions  # type: ignore[import]

# ── Servo identity ────────────────────────────────────────────────────────────
SERVO_ID: Dict[str, int] = {
    "l_ank_roll": 1,   "r_ank_roll": 2,
    "l_ank_pitch": 3,  "r_ank_pitch": 4,
    "l_knee": 5,       "r_knee": 6,
    "l_hip_pitch": 7,  "r_hip_pitch": 8,
    "l_hip_roll": 9,   "r_hip_roll": 10,
    "l_hip_yaw": 11,   "r_hip_yaw": 12,
    "l_sho_pitch": 13, "r_sho_pitch": 14,
    "l_sho_roll": 15,  "r_sho_roll": 16,
    "l_el_pitch": 17,  "r_el_pitch": 18,
    "l_el_yaw": 19,    "r_el_yaw": 20,
    "l_gripper": 21,   "r_gripper": 22,
    "head_pan": 23,    "head_tilt": 24,
}

_EMPTY_SERVOS = {"head_pan", "head_tilt"}
_SKIP_SERVO_IDS = {23, 24}

SERVO_LIMITS: Dict[int, Tuple[int, int]] = {
    13: (333, 835),   # l_sho_pitch
    14: (200, 773),   # r_sho_pitch
    15: (440, 800),   # l_sho_roll
    16: (213, 613),   # r_sho_roll
    17: (440, 653),   # l_el_pitch
    18: (320, 560),   # r_el_pitch
    19: (90, 360),    # l_el_yaw
    20: (573, 880),   # r_el_yaw DAMAGED — never command below 360
}

STAND_PULSE: Dict[str, int] = {
    "l_ank_roll": 500,  "r_ank_roll": 500,
    "l_ank_pitch": 640, "r_ank_pitch": 360,
    "l_knee": 500,      "r_knee": 500,
    "l_hip_pitch": 350, "r_hip_pitch": 650,
    "l_hip_roll": 500,  "r_hip_roll": 500,
    "l_hip_yaw": 500,   "r_hip_yaw": 500,
    "l_sho_pitch": 835, "r_sho_pitch": 165,
    "l_sho_roll": 830,  "r_sho_roll": 170,
    "l_el_pitch": 500,  "r_el_pitch": 500,
    "l_el_yaw": 150,    "r_el_yaw": 850,
    "l_gripper": 500,   "r_gripper": 500,
    "head_pan": 500,    "head_tilt": 500,
}


def clamp_position(servo_id: int, position: int) -> int:
    lo, hi = SERVO_LIMITS.get(servo_id, (0, 1000))
    return max(lo, min(hi, int(position)))


def pulse_to_servos(pulse: Dict[str, int]) -> List[List[int]]:
    servos: List[List[int]] = []
    for name, value in pulse.items():
        if name in _EMPTY_SERVOS or value is None:
            continue
        sid = SERVO_ID.get(name)
        if sid is None or sid in _SKIP_SERVO_IDS:
            continue
        servos.append([sid, clamp_position(sid, value)])
    return servos


def sequence_duration_ms(sequence: List[Tuple[Dict[str, int], int]]) -> int:
    return sum(int(duration) for _, duration in sequence)


# ── Concurrency guard ─────────────────────────────────────────────────────────
class RobotState(str, Enum):
    IDLE         = "IDLE"
    MOTION       = "MOTION"
    CLASSIFYING  = "CLASSIFYING"
    WATCHING     = "WATCHING"
    DEMO_LOCKED  = "DEMO_LOCKED"


_CONFLICTING = {
    RobotState.MOTION,
    RobotState.CLASSIFYING,
    RobotState.WATCHING,
    RobotState.DEMO_LOCKED,
}

_robot_state: RobotState = RobotState.IDLE
_state_lock = threading.Lock()


class RobotBusy(Exception):
    def __init__(self, current: RobotState):
        self.current = current
        super().__init__(f"robot busy: state={current.value}")


def get_state() -> RobotState:
    return _robot_state


def set_state(state: RobotState) -> None:
    global _robot_state
    with _state_lock:
        _robot_state = state


def guard() -> None:
    if _robot_state in _CONFLICTING:
        raise RobotBusy(_robot_state)


class acquire:
    """Context manager: take the robot for ``mode``, restoring IDLE on exit."""

    def __init__(self, mode: RobotState):
        self.mode = mode

    def __enter__(self) -> "acquire":
        set_state(self.mode)
        return self

    def __exit__(self, *exc) -> None:
        set_state(RobotState.IDLE)


# ── Runtime singletons (populated at startup; kept ROS/torch-free at import) ──
_rospy = None
_body_srv = None
_BodyCommandReq = None
_latest_clean_frame = None
_latest_landmarks: List[dict] = []
_classifier = None
_classes: List[str] = []
_device = None

_IMAGENET_MEAN = [0.485, 0.456, 0.406]
_IMAGENET_STD  = [0.229, 0.224, 0.225]

CROSS_DIST_RATIO = 0.8

# Move duration (ms) for pose-mimicry commands returned by /map-features.
_FOLLOW_DURATION_MS = 600


# ── Classifier ────────────────────────────────────────────────────────────────
def load_classifier(model_path: str, device):
    import torch
    import torch.nn as nn
    from torchvision import models

    checkpoint = torch.load(model_path, map_location=device)
    classes = checkpoint["classes"]
    model = models.mobilenet_v3_large(weights=None)
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, len(classes))
    model.load_state_dict(checkpoint["state_dict"])
    model.to(device).eval()
    return model, classes


def _select_device():
    import torch

    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def classify_pose(frame) -> tuple[str, Dict[str, float]]:
    import cv2
    import torch
    import torchvision.transforms as T

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    transform = T.Compose([
        T.ToPILImage(),
        T.Resize((224, 224)),
        T.ToTensor(),
        T.Normalize(mean=_IMAGENET_MEAN, std=_IMAGENET_STD),
    ])
    tensor = transform(rgb).unsqueeze(0).to(_device)

    with torch.no_grad():
        logits = _classifier(tensor)
        probs = torch.softmax(logits, dim=1)[0].cpu().tolist()

    pct = {cls: round(100.0 * p, 2) for cls, p in zip(_classes, probs)}
    top = max(pct, key=pct.get)
    return top, pct


# ── ROS plumbing ──────────────────────────────────────────────────────────────
def _ros_image_to_bgr(msg):
    import numpy as np

    return np.ndarray((msg.height, msg.width, 3), dtype=np.uint8, buffer=msg.data).copy()


def _clean_frame_cb(msg):
    global _latest_clean_frame
    try:
        _latest_clean_frame = _ros_image_to_bgr(msg)
    except Exception:  # noqa: BLE001
        pass


def _landmarks_cb(msg):
    """Merge the /landmarks topic's separate norm + world lists into the combined
    per-landmark dicts compute_joint_targets expects: image coords under x/y and
    world coords under xw/yw/zw. _hands_close still works off the x/y fields.
    """
    global _latest_landmarks
    try:
        payload = json.loads(msg.data)
        norm = payload.get("norm_landmarks", [])
        world = payload.get("world_landmarks", [])
        merged: List[dict] = []
        for i, n in enumerate(norm):
            entry = {
                "x": n["x"], "y": n["y"], "z": n["z"],
                "visibility": n.get("visibility", 0.0),
            }
            if i < len(world):
                w = world[i]
                entry["xw"], entry["yw"], entry["zw"] = w["x"], w["y"], w["z"]
            merged.append(entry)
        _latest_landmarks = merged
    except Exception:  # noqa: BLE001
        pass


def _init_ros() -> None:
    global _rospy, _body_srv, _BodyCommandReq

    import rospy
    from sensor_msgs.msg import Image
    from std_msgs.msg import String

    _rospy = rospy
    rospy.init_node("robot_server", anonymous=True, disable_signals=True)

    from ainex_demo.srv import BodyCommand, BodyCommandRequest  # type: ignore

    _BodyCommandReq = BodyCommandRequest
    rospy.loginfo("[robot_server] waiting for /body_commands service...")
    rospy.wait_for_service("/body_commands", timeout=15.0)
    _body_srv = rospy.ServiceProxy("/body_commands", BodyCommand)

    rospy.Subscriber("/clean_frame", Image, _clean_frame_cb, queue_size=1)
    rospy.Subscriber("/landmarks", String, _landmarks_cb, queue_size=10)
    rospy.loginfo("[robot_server] ROS ready — body service + vision topics wired")


def _clamp_sequence(
    sequence: List[Tuple[Dict[str, int], int]],
) -> List[Tuple[Dict[str, int], int]]:
    """Clamp every pulse in a motion sequence to its servo's safe range.

    Named motions in motions.py are authored data, not computed at request time —
    unlike /move, nothing upstream clamps them before they reach here. Some poses
    (e.g. dab, superhero, muscles, stand_low) carry r_el_yaw values above its 850
    ceiling, so without this the raw pose data would be sent straight to the
    ROS body service, past the limit that was added after servo 20 was burned.
    """
    clamped = []
    for pulse, dur in sequence:
        safe_pulse = {
            name: (clamp_position(SERVO_ID[name], value) if name in SERVO_ID and value is not None else value)
            for name, value in pulse.items()
        }
        clamped.append((safe_pulse, dur))
    return clamped


def _call_body_service(sequence, global_duration: Optional[float] = None) -> float:
    if _body_srv is None or _BodyCommandReq is None:
        raise RuntimeError("body service not initialized")
    sequence = _clamp_sequence(sequence)
    commands_json = json.dumps([[pulse, dur] for pulse, dur in sequence])
    req = _BodyCommandReq(
        commands_json=commands_json,
        global_duration=float(global_duration or 0.0),
    )
    resp = _body_srv(req)
    return getattr(resp, "duration_ms", sequence_duration_ms(sequence))


async def _run_sequence(sequence, global_duration: Optional[float] = None) -> float:
    with acquire(RobotState.MOTION):
        return await asyncio.get_event_loop().run_in_executor(None, lambda: _call_body_service(sequence, global_duration))


# ── FastAPI app ───────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _classifier, _classes, _device
    _init_ros()
    model_path = os.getenv(
        "CLASSIFIER_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "model", "pose_classifier.pt"),
    )
    _device = _select_device()
    _classifier, _classes = load_classifier(model_path, _device)
    print(f"[robot_server] classifier on {_device} — classes: {_classes}", flush=True)
    yield


app = FastAPI(title="AiNex Robot Server", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class MotionRequest(BaseModel):
    name: str
    global_duration: Optional[float] = None


class StateRequest(BaseModel):
    mode: str


class ServoMove(BaseModel):
    servo_id: int
    position: int
    duration_ms: int


class FeedbackRequest(BaseModel):
    servo_ids: List[int]


@app.get("/health")
def health():
    return {"status": "ok", "state": get_state().value, "classes": _classes}


@app.get("/state")
def read_state():
    return {"state": get_state().value}


@app.post("/state")
def write_state(req: StateRequest):
    try:
        set_state(RobotState(req.mode))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"unknown state: {req.mode}")
    return {"state": get_state().value}


@app.post("/motion")
async def motion(req: MotionRequest):
    sequence = motions.get_motion(req.name)
    if sequence is None:
        raise HTTPException(status_code=404, detail=f"unknown motion: {req.name}")
    duration_ms = await _run_sequence(sequence, req.global_duration)
    return {"status": "done", "motion": req.name, "duration_ms": duration_ms}


@app.post("/classify")
async def classify():
    import cv2

    if _latest_clean_frame is None:
        raise HTTPException(status_code=503, detail="no camera frame available yet")

    frame = _latest_clean_frame.copy()
    with acquire(RobotState.CLASSIFYING):
        top_class, probabilities = await asyncio.get_event_loop().run_in_executor(None, lambda: classify_pose(frame))

    ok, buf = cv2.imencode(".jpg", frame)
    image_b64 = base64.b64encode(buf.tobytes()).decode("ascii") if ok else None
    return {
        "class": top_class,
        "probabilities": probabilities,
        "image_b64": image_b64,
        "image_format": "jpeg",
    }


@app.post("/map-features")
async def map_features():
    """Retarget the latest MediaPipe landmarks to servo commands (replaces the
    MobileNetV3 /classify path). Computes locally from the /landmarks + /clean_frame
    topics; returns the commands, the landmarks, and the frame they came from.
    The caller executes the commands via /move."""
    try:
        import cv2

        from pose_to_robot import (  # type: ignore[import]  # vendored — see pose_to_robot.py
            compute_joint_targets,
            hips_detected,
            targets_to_hardware_servo_commands,
        )
    except Exception as e:  # noqa: BLE001
        # An uncaught import/exec error here can crash the connection before
        # CORSMiddleware attaches headers to the error response, which the
        # browser then misreports as a CORS failure instead of the real 500.
        # Raising HTTPException instead gives a normal response the middleware
        # can still decorate, and surfaces the actual failure to the caller.
        raise HTTPException(status_code=500, detail=f"map-features import failed: {e!r}")

    if _latest_clean_frame is None:
        raise HTTPException(status_code=503, detail="no camera frame available yet")

    try:
        frame = _latest_clean_frame.copy()
        body = _latest_landmarks or []
        ok, buf = cv2.imencode(".jpg", frame)
        image_b64 = base64.b64encode(buf.tobytes()).decode("ascii") if ok else None

        # Arm retargeting is anchored on the hips; without them we'd only move the
        # head, so ask the caller to reframe and retake instead.
        if not hips_detected(body):
            return {
                "pose_detected": False,
                "detail": "Make sure your wrists, shoulders, and hips are visible in the frame!",
                "commands": [],
                "targets": {},
                "body_landmarks": body,
                "image_b64": image_b64,
                "image_format": "jpeg",
            }

        # No head-pose solve on the Pi vision node, so head targets are left neutral.
        targets = compute_joint_targets(body, None)

        # Middle step: map the retargeted joint *radians* onto physical servo pulses
        # using the per-joint hardware calibration (stand-pulse anchors, mirror-mount
        # directions, damaged-servo limits) rather than the sim's uniform 500-centre map.
        commands = targets_to_hardware_servo_commands(targets, _FOLLOW_DURATION_MS)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"map-features failed: {e!r}")

    return {
        "pose_detected": True,
        "commands": [
            {"servo_id": c.servo_id, "position": c.position, "duration_ms": c.duration_ms}
            for c in commands
        ],
        "targets": targets,
        "body_landmarks": body,
        "image_b64": image_b64,
        "image_format": "jpeg",
    }


def _hands_close(norm_lm: List[dict]) -> bool:
    import math

    if len(norm_lm) <= 16:
        return False
    l_sho, r_sho = norm_lm[11], norm_lm[12]
    l_wri, r_wri = norm_lm[15], norm_lm[16]

    sho_w = math.hypot(l_sho["x"] - r_sho["x"], l_sho["y"] - r_sho["y"])
    if sho_w < 0.02:
        return False
    wri_d = math.hypot(l_wri["x"] - r_wri["x"], l_wri["y"] - r_wri["y"])
    return (wri_d / sho_w) < CROSS_DIST_RATIO


@app.get("/watch-for-action")
async def watch_for_action(timeout: float = 30.0):
    deadline = time.time() + timeout
    with acquire(RobotState.WATCHING):
        while time.time() < deadline:
            if _hands_close(_latest_landmarks):
                return {"detected": True, "timeout": False}
            await asyncio.sleep(0.1)
    return {"detected": False, "timeout": True}


@app.post("/move")
async def move(moves: List[ServoMove]):
    try:
        guard()
    except RobotBusy as e:
        raise HTTPException(status_code=429, detail=str(e))

    by_duration: Dict[int, Dict[str, int]] = {}
    id_to_name = {v: k for k, v in SERVO_ID.items()}
    for m in moves:
        name = id_to_name.get(m.servo_id)
        if name is None:
            continue
        dur = max(100, m.duration_ms)
        by_duration.setdefault(dur, {})[name] = clamp_position(m.servo_id, m.position)

    sequence = [(pulse, dur) for dur, pulse in by_duration.items()]
    if not sequence:
        return {"moved": 0}
    await _run_sequence(sequence)
    return {"moved": sum(len(p) for p in by_duration.values())}


@app.post("/stand")
async def stand():
    await _run_sequence(motions.get_motion("stand"))
    return {"status": "standing"}


@app.post("/feedback")
def feedback(req: FeedbackRequest):
    id_to_name = {v: k for k, v in SERVO_ID.items()}
    results = [
        {
            "servo_id": sid,
            "position": STAND_PULSE.get(id_to_name.get(sid, ""), 500),
            "temperature": 35,
            "voltage": 11100,
        }
        for sid in req.servo_ids
    ]
    return {"feedback": results}


@app.get("/positions")
def positions():
    id_to_name = {v: k for k, v in SERVO_ID.items()}
    return {"positions": {sid: STAND_PULSE.get(id_to_name.get(sid, ""), 500) for sid in range(1, 25)}}


def main():
    port = int(os.getenv("AGENT_PORT", "9000"))
    print(f"[robot_server] starting on 0.0.0.0:{port}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
