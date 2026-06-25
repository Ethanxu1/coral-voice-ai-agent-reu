from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .frame_broadcaster import FrameBroadcaster
from .pose_estimator import PoseEstimator

logger = logging.getLogger("vision")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

_estimator: Optional[PoseEstimator] = None
_broadcaster: Optional[FrameBroadcaster] = None
_vision_thread: Optional[threading.Thread] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_pose_throttle_fps = 30
_last_pose_time = 0.0


def _vision_loop():
    assert _estimator is not None and _broadcaster is not None
    logger.info("Vision thread started — loading models and opening camera...")
    _estimator.open()
    logger.info("Vision thread ready — publishing frames")
    global _last_pose_time
    while _estimator.is_running:
        result = _estimator.process_frame()
        if result is None:
            time.sleep(0.033)
            continue

        _broadcaster.publish_video(result.jpeg_bytes)

        now = time.time()
        if now - _last_pose_time >= 1.0 / _pose_throttle_fps:
            _last_pose_time = now
            pose_dict = result.to_pose_dict()
            pose_dict["stability"] = _estimator.stability.status_dict()
            if _estimator.pnp_fail_count > 10:
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
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
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


@app.get("/health")
async def health():
    cal = _estimator.calibration.to_dict() if _estimator else {}
    return {"status": "ok", "calibrated": cal.get("state") == "calibrated", "calibration": cal}


def main():
    uvicorn.run("coral_agent.vision.vision_server:app", host="0.0.0.0", port=8001, reload=False)


if __name__ == "__main__":
    main()
