from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import geometry, leg_modes, pose_classifier
from .frame_broadcaster import FrameBroadcaster
from .pose_estimator import PoseEstimator
from .pose_to_robot import (
    compute_joint_targets,
    hips_detected,
    knees_confidently_visible,
    targets_to_servo_commands,
)

logger = logging.getLogger("vision")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

_estimator: Optional[PoseEstimator] = None
_broadcaster: Optional[FrameBroadcaster] = None
_vision_thread: Optional[threading.Thread] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_pose_throttle_fps = 30
_last_pose_time = 0.0

# Latest frame + landmarks, kept for the demo's /features and /watch-for-action.
# Updated every vision-loop iteration so they never need to touch the camera.
_latest_jpeg: Optional[bytes] = None
# Un-annotated BGR frame (no skeleton overlay). Fed to the pose classifier so it
# sees clean images like it was trained on — matches the Pi's /clean_frame.
_latest_clean_frame = None
_latest_landmarks: list = []
# Latest head pose (dict with yaw/pitch/roll), consumed by /features so the
# pose→robot retargeting can drive head_pan/head_tilt. None when no face solve.
_latest_head_pose: Optional[dict] = None
# Subject-selection metadata published with pose updates.
_latest_selection_state: str = "idle"
_latest_selected_subject_id: Optional[str] = None
_latest_subjects: list = []

# MobileNetV3 pose classifier — lazily loaded on first /classify (keeps torch off
# the startup path and optional unless the demo actually classifies).
_classifier = None
_classes: list = []
_device = None
_classifier_lock = threading.Lock()

_DEFAULT_CLASSIFIER_PATH = str(
    Path(__file__).resolve().parent / "models" / "pose_classifier.pt"
)


def _vision_loop():
    assert _estimator is not None and _broadcaster is not None
    logger.info("Vision thread started — loading models and opening camera...")
    _estimator.open()
    logger.info("Vision thread ready — publishing frames")
    global _last_pose_time, _latest_jpeg, _latest_clean_frame, _latest_landmarks, _latest_head_pose
    global _latest_selection_state, _latest_selected_subject_id, _latest_subjects
    while _estimator.is_running:
        result = _estimator.process_frame()
        if result is None:
            time.sleep(0.033)
            continue

        _broadcaster.publish_video(result.jpeg_bytes)
        # Keep the freshest frame + landmarks for /features and /watch-for-action.
        _latest_jpeg = result.jpeg_bytes
        _latest_clean_frame = result.clean_frame
        _latest_landmarks = result.body_landmarks
        _latest_head_pose = result.head_pose.to_dict() if result.head_pose else None
        _latest_selection_state = result.selection_state
        _latest_selected_subject_id = result.selected_subject_id
        _latest_subjects = result.subjects

        now = time.time()
        if now - _last_pose_time >= 1.0 / _pose_throttle_fps:
            _last_pose_time = now
            pose_dict = result.to_pose_dict()
            pose_dict["stability"] = _estimator.stability.status_dict()
            if _estimator.pnp_fail_count > 10 and _estimator._pose_detector is _estimator._pose_detector_single:
                pose_dict["type"] = "tracking_lost"
                pose_dict["reason"] = "no_person_detected"
            _broadcaster.publish_pose(pose_dict)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _estimator, _broadcaster, _vision_thread, _loop
    _loop = asyncio.get_running_loop()
    logger.info("Vision server starting — initialising estimator and broadcaster")
    _estimator = PoseEstimator()
    _broadcaster = FrameBroadcaster(_loop)
    _vision_thread = threading.Thread(target=_vision_loop, daemon=True)
    _vision_thread.start()
    logger.info("Vision server ready on port 8001 (models loading in background)")
    yield
    if _estimator:
        _estimator.close()


app = FastAPI(title="Coral Vision Service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000","http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _mjpeg_generator(q: asyncio.Queue):
    boundary = b"--frame"
    try:
        while True:
            jpeg = await asyncio.wait_for(q.get(), timeout=5.0)
            yield boundary + b"\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
    except (asyncio.TimeoutError, GeneratorExit):
        pass
    finally:
        if _broadcaster:
            _broadcaster.unsubscribe_video(q)


@app.get("/video_feed")
async def video_feed():
    assert _broadcaster is not None
    q = _broadcaster.subscribe_video()
    return StreamingResponse(
        _mjpeg_generator(q),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.websocket("/ws/pose")
async def websocket_pose(websocket: WebSocket):
    await websocket.accept()
    client = websocket.client
    logger.info("WebSocket client connected: %s", client)
    assert _broadcaster is not None
    q = _broadcaster.subscribe_pose()
    try:
        while True:
            try:
                data = await asyncio.wait_for(q.get(), timeout=2.0)
                await websocket.send_text(json.dumps(data))
            except asyncio.TimeoutError:
                # Send a keepalive ping so the browser doesn't close the connection
                # while the vision system is still warming up
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected: %s", client)
    except Exception as exc:
        logger.warning("WebSocket error for %s: %s", client, exc)
    finally:
        _broadcaster.unsubscribe_pose(q)


def _ensure_classifier() -> None:
    """Load the MobileNetV3 classifier on first use (thread-safe, idempotent)."""
    global _classifier, _classes, _device
    if _classifier is not None:
        return
    with _classifier_lock:
        if _classifier is not None:
            return
        model_path = os.getenv("CLASSIFIER_PATH", _DEFAULT_CLASSIFIER_PATH)
        if not os.path.exists(model_path):
            raise HTTPException(status_code=503, detail=f"classifier model not found: {model_path}")
        _device = pose_classifier.select_device()
        _classifier, _classes = pose_classifier.load_classifier(model_path, _device)
        logger.info("Pose classifier loaded on %s — classes: %s", _device, _classes)


@app.post("/classify")
async def classify():
    """Classify the current camera frame (MobileNetV3) → class + probabilities + image."""
    if _latest_jpeg is None:
        raise HTTPException(status_code=503, detail="no camera frame available yet")

    # Classify the CLEAN frame (no skeleton overlay) — the model was trained on
    # clean photos. The returned preview stays the annotated frame for the UI.
    top_class, probabilities = await _classify_clean_frame()
    return {
        "class": top_class,
        "probabilities": probabilities,
        "image_b64": base64.b64encode(_latest_jpeg).decode("ascii"),
        "image_format": "jpeg",
    }


async def _classify_clean_frame() -> tuple[str, dict]:
    """Run the pose classifier on the latest clean (un-annotated) frame."""
    _ensure_classifier()
    frame = _latest_clean_frame
    if frame is None:
        raise HTTPException(status_code=503, detail="no clean camera frame available yet")
    return await asyncio.get_event_loop().run_in_executor(
        None, lambda: pose_classifier.classify_frame(frame, _classifier, _classes, _device)
    )


# Move duration (ms) for pose-mimicry commands. Slow enough to look deliberate,
# fast enough that the child sees Coral react promptly to their pose.
_FOLLOW_DURATION_MS = 1000


@app.post("/map-features")
async def map_features(leg_mode: str = "retarget"):
    """Retarget the latest MediaPipe landmarks to robot servo commands.

    Instead of picking a canned pose class, we map the person's actual body
    geometry to joint angles and hand back the servo commands for the caller to
    execute. Returns the landmarks and the frame they were computed from so the
    UI can show what Coral saw.

    The arms always use the live pelvis/torso-frame retargeting. The `leg_mode`
    query param (default "retarget") selects how the *legs* are driven — see
    leg_modes.py:
      "retarget"  live pelvis-frame hip pitch/roll + knee bend (default).
      "legacy"    the old anatomically-wrong atan2 mapping (hip_yaw ← swing).
      "classify"  MobileNetV3 → snap legs to the matching canned pose's stance.
      "buckets"   classify knee/ankle bend depth and hip yaw into discrete
                  stances (low/stand/high, in/stand/out) and snap to each
                  bucket's fixed target.
    """
    if leg_mode not in leg_modes.LEG_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown leg_mode '{leg_mode}'; expected one of {leg_modes.LEG_MODES}",
        )

    # Unconditional — logs every /map-features call's leg_mode regardless of
    # which branch below runs, so "is buckets actually selected?" is answerable
    # from this one line instead of inferring it from the resulting joint values
    # (e.g. non-zero/varying hip_roll is a signature of "retarget", since
    # "buckets" always pins hip_roll to stand).
    logger.info("map-features: leg_mode=%s", leg_mode)

    if _latest_jpeg is None:
        raise HTTPException(status_code=503, detail="no camera frame available yet")

    body = _latest_landmarks or []
    # _latest_jpeg already has the knee-bend/hip-yaw angle arcs baked in — drawn
    # continuously on every live frame by PoseEstimator.process_frame, not just
    # on this single capture (see pose_estimator._draw_bucket_angle_arcs).
    image_b64 = base64.b64encode(_latest_jpeg).decode("ascii")

    # Debug: log the raw knee visibilities so we can see why legs did/didn't
    # clear the 0.6 knee gate in pose_to_robot for this capture.
    def _knee_vis(idx: int) -> str:
        return f"{body[idx]['visibility']:.3f}" if idx < len(body) else "n/a"

    logger.info(
        "map-features knee visibility — left=%s right=%s",
        _knee_vis(geometry.LEFT_KNEE),
        _knee_vis(geometry.RIGHT_KNEE),
    )

    # The arm retargeting is anchored on the hips; without them we'd only be able
    # to move the head, so ask the caller to reframe and retake instead.
    if not hips_detected(body):
        return {
            "pose_detected": False,
            "detail": "Make sure your wrists, shoulders, and hips are visible in the frame!",
            "commands": [],
            "targets": {},
            "leg_mode": leg_mode,
            "body_landmarks": body,
            "image_b64": image_b64,
            "image_format": "jpeg",
        }

    head = _latest_head_pose
    targets = compute_joint_targets(body, head)
    pose_class = None

    if leg_mode != "retarget":
        # Arms keep the live retargeting; replace the pelvis-frame legs with the
        # selected mode's legs.
        targets = leg_modes.strip_legs(targets)
        if leg_mode == "legacy":
            # Authored in hardware units → convert to sim radians.
            targets.update(leg_modes.leg_pulses_to_targets(leg_modes.legacy_leg_pulses(body)))
        elif leg_mode == "buckets":
            # Bucket tables are already authored in sim radians. Hip yaw is
            # leg-independent, so knee_ankle + each side's hip yaw are logged
            # separately.
            knee_ankle, hip_yaw_l, hip_yaw_r = leg_modes.classify_buckets(body)
            logger.info(
                "buckets: knee_ankle=%s hip_yaw_l=%s hip_yaw_r=%s",
                knee_ankle, hip_yaw_l, hip_yaw_r,
            )
            targets.update(leg_modes.combine_bucket_targets(knee_ankle, hip_yaw_l, hip_yaw_r))
        else:  # "classify"
            pose_class, probs = await _classify_clean_frame()
            conf = probs.get(pose_class) if isinstance(probs, dict) else None
            logger.info(
                "classify: pose=%s%s",
                pose_class,
                f" ({conf:.1f}%)" if isinstance(conf, (int, float)) else "",
            )
            leg_pulses = leg_modes.classify_leg_pulses(pose_class)
            targets.update(leg_modes.leg_pulses_to_targets(leg_pulses))

    # Mode-independent knee gate: if the knees aren't confidently visible, stand
    # the legs regardless of leg_mode. compute_joint_targets already does this for
    # "retarget", but legacy/classify compute their own leg pulses above and would
    # otherwise drive the legs off an unseen lower body.
    if not knees_confidently_visible(body):
        targets = leg_modes.strip_legs(targets)
        targets.update(leg_modes.stand_leg_targets())

    # Definitive check: the exact leg-only values about to be dispatched, so we
    # can tell a computation bug (wrong values here) apart from a downstream
    # dispatch/rendering issue (right values here, wrong result in the sim) or
    # a mix-up with arm motion (which legitimately moves live every capture).
    leg_targets_final = {k: round(v, 4) for k, v in targets.items() if k in leg_modes.LEG_JOINTS}
    logger.info("map-features: final leg targets = %s", leg_targets_final)

    commands = targets_to_servo_commands(targets, _FOLLOW_DURATION_MS)
    return {
        "pose_detected": True,
        "commands": [
            {"servo_id": c.servo_id, "position": c.position, "duration_ms": c.duration_ms}
            for c in commands
        ],
        "targets": targets,
        "leg_mode": leg_mode,
        "pose_class": pose_class,
        "body_landmarks": body,
        "image_b64": image_b64,
        "image_format": "jpeg",
    }


@app.get("/watch-for-action")
async def watch_for_action(timeout: float = 30.0):
    """Block until the 'hands close' gesture is seen, or until timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pose_classifier.hands_close(_latest_landmarks):
            return {"detected": True, "timeout": False}
        await asyncio.sleep(0.1)
    return {"detected": False, "timeout": True}


@app.post("/calibrate/start")
async def calibrate_start():
    assert _estimator is not None
    _estimator.calibration.start()
    return {"status": "collecting", "message": "Calibration started"}


@app.post("/calibrate/reset")
async def calibrate_reset():
    assert _estimator is not None
    _estimator.calibration.reset()
    return {"status": "idle", "message": "Calibration reset"}


@app.post("/capture/stable_position/start")
async def capture_stable_position_start():
    assert _estimator is not None
    started = _estimator.stability.start()
    return {"status": "ok" if started else "ignored", "stability": _estimator.stability.status_dict()}


@app.post("/capture/stable_position/continue")
async def capture_stable_position_continue():
    assert _estimator is not None
    resumed = _estimator.stability.continue_live()
    return {"status": "ok" if resumed else "ignored", "stability": _estimator.stability.status_dict()}


@app.get("/capture/stable_position/frozen")
async def capture_stable_position_frozen():
    assert _estimator is not None
    frozen = _estimator.stability.frozen_result()
    if frozen is None:
        raise HTTPException(status_code=409, detail="no frozen frame")
    return frozen.to_pose_dict()


@app.post("/settings/angle-arcs")
async def set_angle_arcs(enabled: bool = True):
    """Toggle the knee-bend/hip-yaw debug angle arcs drawn on every live frame
    (see pose_estimator._draw_bucket_angle_arcs). Applies immediately to the
    running vision loop — no restart needed, unlike most other changes here."""
    if _estimator is None:
        raise HTTPException(status_code=503, detail="vision estimator not initialized yet")
    _estimator.show_angle_arcs = enabled
    logger.info("angle-arcs: enabled=%s", enabled)
    return {"show_angle_arcs": enabled}


@app.get("/health")
async def health():
    cal = _estimator.calibration.to_dict() if _estimator else {}
    return {"status": "ok", "calibrated": cal.get("state") == "calibrated", "calibration": cal}


# ── Subject selection endpoints ───────────────────────────────────────────────

@app.post("/subject-selection/start")
async def subject_selection_start():
    """Enable multi-person detection and start selecting a subject."""
    if _estimator is None:
        raise HTTPException(status_code=503, detail="vision estimator not initialized yet")
    _estimator.set_multi_person_mode(True)
    _estimator.subject_selector.start()
    logger.info("Subject selection started (multi-person mode)")
    return _estimator.subject_selector.status()


@app.post("/subject-selection/reset")
async def subject_selection_reset():
    """Clear the current selection and return to selecting mode."""
    if _estimator is None:
        raise HTTPException(status_code=503, detail="vision estimator not initialized yet")
    _estimator.subject_selector.reset()
    logger.info("Subject selection reset")
    return _estimator.subject_selector.status()


@app.post("/subject-selection/stop")
async def subject_selection_stop():
    """Exit selection mode and return to single-person tracking."""
    if _estimator is None:
        raise HTTPException(status_code=503, detail="vision estimator not initialized yet")
    _estimator.set_multi_person_mode(False)
    _estimator.subject_selector.reset()
    logger.info("Subject selection stopped (single-person mode)")
    return {"state": "idle", "selected_subject_id": None}


@app.get("/subject-selection/status")
async def subject_selection_status():
    """Return current selection state and any detected subjects."""
    if _estimator is None:
        raise HTTPException(status_code=503, detail="vision estimator not initialized yet")
    status = _estimator.subject_selector.status()
    status["subjects"] = _latest_subjects
    return status


@app.get("/subject-selection/tuning")
async def subject_selection_tuning_get():
    """Return live-tunable re-ID parameters + their allowed ranges."""
    if _estimator is None:
        raise HTTPException(status_code=503, detail="vision estimator not initialized yet")
    from .subject_selector import TUNABLE_PARAMS
    return {
        "values": _estimator.subject_selector.get_tuning(),
        "params": TUNABLE_PARAMS,
    }


@app.post("/subject-selection/tuning")
async def subject_selection_tuning_set(updates: dict = Body(...)):
    """Apply a partial update to the tunable re-ID parameters (unknown keys ignored)."""
    if _estimator is None:
        raise HTTPException(status_code=503, detail="vision estimator not initialized yet")
    values = _estimator.subject_selector.update_tuning(updates or {})
    logger.info("subject-selection tuning updated: %s", {k: v for k, v in (updates or {}).items()})
    return {"values": values}


def main():
    uvicorn.run("vision.vision_server:app", host="0.0.0.0", port=8001, reload=False)


if __name__ == "__main__":
    main()
