from __future__ import annotations

import logging
import math
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from mediapipe.tasks.python.vision import drawing_utils as mp_drawing

from . import geometry
from .calibration import CalibrationManager, CalibrationState
from .smpl_fit import UserShape

# Model asset paths (downloaded on first run)
_MODELS_DIR = Path(__file__).parent / "models"
_POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
)
_FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/latest/face_landmarker.task"
)

# Standard 6-point 3D head model in mm, origin at nose tip
_HEAD_3D_POINTS = np.array([
    [0.0,     0.0,     0.0   ],  # Nose tip        → face landmark 1
    [0.0,    -63.6,   -12.5  ],  # Chin             → 152
    [-43.3,   32.7,   -26.0  ],  # Left eye outer   → 263
    [43.3,    32.7,   -26.0  ],  # Right eye outer  → 33
    [-77.5,  -14.9,   -79.4  ],  # Left ear         → 287
    [77.5,   -14.9,   -79.4  ],  # Right ear        → 57
], dtype=np.float64)

_FACE_LM_INDICES = [1, 152, 263, 33, 287, 57]
_FACE_LM_NAMES = ["nose_tip", "chin", "left_eye", "right_eye", "left_ear", "right_ear"]

# Pose connections as index pairs for overlay drawing
_POSE_CONNECTIONS = [
    (c.start, c.end)
    for c in mp_vision.PoseLandmarksConnections.POSE_LANDMARKS
]

# Special pose indices
_NOSE_IDX = 0
_LEFT_EAR_IDX = 7
_RIGHT_EAR_IDX = 8
_MOUTH_LEFT_IDX = 9
_MOUTH_RIGHT_IDX = 10


class OneEuroFilter:
    """Adaptive low-pass filter: low cutoff when still (kills jitter), high cutoff when moving (preserves responsiveness)."""

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.1, d_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x_prev: Optional[float] = None
        self._dx_hat: float = 0.0
        self._t_prev: Optional[float] = None

    def _alpha(self, cutoff: float, dt: float) -> float:
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def filter(self, x: float, t: float) -> float:
        if self._t_prev is None:
            self._t_prev = t
            self._x_prev = x
            return x
        dt = max(t - self._t_prev, 1e-6)
        dx = (x - self._x_prev) / dt  # type: ignore[operator]
        alpha_d = self._alpha(self.d_cutoff, dt)
        self._dx_hat = alpha_d * dx + (1 - alpha_d) * self._dx_hat
        cutoff = self.min_cutoff + self.beta * abs(self._dx_hat)
        alpha = self._alpha(cutoff, dt)
        x_hat = alpha * x + (1 - alpha) * self._x_prev  # type: ignore[operator]
        self._x_prev = x_hat
        self._t_prev = t
        return x_hat


def _download_model(url: str, dest: Path):
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[vision] Downloading {dest.name}...")
    urllib.request.urlretrieve(url, dest)
    print(f"[vision] Downloaded {dest.name}")


@dataclass
class HeadPose:
    yaw: float
    pitch: float
    roll: float
    raw_yaw: float
    raw_pitch: float
    raw_roll: float

    def to_dict(self) -> dict:
        return {
            "yaw": round(self.yaw, 2),
            "pitch": round(self.pitch, 2),
            "roll": round(self.roll, 2),
            "raw_yaw": round(self.raw_yaw, 2),
            "raw_pitch": round(self.raw_pitch, 2),
            "raw_roll": round(self.raw_roll, 2),
        }


@dataclass
class FrameResult:
    body_landmarks: list[dict]
    face_landmarks: list[dict]
    head_pose: Optional[HeadPose]
    jpeg_bytes: bytes
    calibration: dict
    timestamp: float = field(default_factory=time.time)
    # Un-annotated BGR frame (no skeleton/text overlay). Carried so consumers
    # like the pose classifier can run on the clean image — the model was
    # trained on clean photos, so the drawn overlay is a train/test mismatch.
    # Mirrors the Pi vision node's separate /clean_frame topic.
    clean_frame: Optional["np.ndarray"] = None

    def to_pose_dict(self) -> dict:
        return {
            "type": "pose_update",
            "timestamp": self.timestamp,
            "body_landmarks": self.body_landmarks,
            "face_landmarks": self.face_landmarks,
            "head_pose": self.head_pose.to_dict() if self.head_pose else None,
            "calibration": self.calibration,
        }


# ── Stable-position capture ──────────────────────────────────────────────────
# Ported from ak-maker/ainex_skeleton_following@scott/full-pipeline (nodes/webserver.py).
# Picks the frame from a short buffer whose pose is closest to its neighbours
# (gaussian-weighted L2 distance over MediaPipe landmark coordinates).
_STABILITY_N = 3
_STABILITY_SIGMA = 1.0
_REQUIRED_LANDMARKS = (11, 12, 13, 14, 15, 16)  # shoulders, elbows, wrists
_VISIBILITY_THRESH = 0.4
_COUNTDOWN_SECONDS = 3.0
_COLLECT_SECONDS = 3.0


def _frame_distance(a: list[dict], b: list[dict]) -> float:
    total = 0.0
    for la, lb in zip(a, b):
        dx = la["x"] - lb["x"]
        dy = la["y"] - lb["y"]
        dz = la["z"] - lb["z"]
        total += math.sqrt(dx * dx + dy * dy + dz * dz)
    return total


def _stability_score(frames: list[list[dict]], idx: int, N: int, sigma: float) -> float:
    score = 0.0
    for k in range(-N, N + 1):
        if k == 0:
            continue
        j = idx + k
        if 0 <= j < len(frames):
            score += _frame_distance(frames[idx], frames[j]) * math.exp(-k * k / (2.0 * sigma * sigma))
    return score


def _most_stable_index(frames: list[list[dict]], N: int = _STABILITY_N, sigma: float = _STABILITY_SIGMA) -> int:
    if len(frames) < 2 * N + 1:
        return len(frames) // 2
    scores = [_stability_score(frames, i, N, sigma) for i in range(N, len(frames) - N)]
    return N + scores.index(min(scores))


def _is_valid_skel_frame(body_lms: list[dict]) -> bool:
    if not body_lms:
        return False
    for idx in _REQUIRED_LANDMARKS:
        if idx >= len(body_lms):
            return False
        if body_lms[idx].get("visibility", 0.0) < _VISIBILITY_THRESH:
            return False
    return True


@dataclass
class _BufferEntry:
    body_landmarks: list[dict]
    face_landmarks: list[dict]
    head_pose: Optional["HeadPose"]
    clean_bgr: np.ndarray  # raw frame before overlay; small (~900KB), kept few seconds only


_SMPL_FIT_LOG = logging.getLogger("smpl_fit")

# Signature of the optional SMPL-fit hook fired from StabilityCapture._finalize.
FitHook = Callable[[list[list[dict]]], Optional[UserShape]]


class StabilityCapture:
    """State machine that drives the capture-stable-position UX from the vision loop.

    States: idle → countdown → collecting → fitting → frozen → (continue) → idle.
    The ``fitting`` state runs synchronously inside the vision thread; the call
    site (``PoseEstimator``) injects ``fit_hook`` so the SMPL stack stays
    optional — if it's missing or the fit fails, we skip straight to ``frozen``.

    Lives in the vision thread but ``start()`` / ``continue_live()`` are called
    from the FastAPI thread, so all mutating operations take a lock.
    """

    def __init__(self, fit_hook: Optional[FitHook] = None):
        self._lock = threading.Lock()
        self._state = "idle"
        self._t0 = 0.0
        self._buffer: list[_BufferEntry] = []
        self._frozen: Optional[FrameResult] = None
        self._fit_hook = fit_hook
        self._user_shape: Optional[UserShape] = None

    @property
    def user_shape(self) -> Optional[UserShape]:
        return self._user_shape

    # ── Public API (called from FastAPI thread) ────────────────────────────
    def start(self) -> bool:
        with self._lock:
            if self._state != "idle":
                return False
            self._state = "countdown"
            self._t0 = time.time()
            self._buffer.clear()
            self._frozen = None
            return True

    def continue_live(self) -> bool:
        with self._lock:
            if self._state != "frozen":
                return False
            self._state = "idle"
            self._buffer.clear()
            self._frozen = None
            return True

    def status_dict(self) -> dict:
        with self._lock:
            now = time.time()
            countdown_remaining = 0.0
            collection_progress = 0.0
            if self._state == "countdown":
                countdown_remaining = max(0.0, _COUNTDOWN_SECONDS - (now - self._t0))
            elif self._state == "collecting":
                collection_progress = min(1.0, (now - self._t0) / _COLLECT_SECONDS)
            elif self._state in ("fitting", "frozen"):
                collection_progress = 1.0
            d: dict = {
                "state": self._state,
                "countdown_remaining": round(countdown_remaining, 2),
                "collection_progress": round(collection_progress, 3),
            }
            if self._user_shape is not None:
                d["shape_ready"] = True
                d["segment_lengths"] = {
                    "upper_arm": round(self._user_shape.upper_arm_len, 4),
                    "forearm": round(self._user_shape.forearm_len, 4),
                    "thigh": round(self._user_shape.thigh_len, 4),
                    "shin": round(self._user_shape.shin_len, 4),
                    "shoulder_span": round(self._user_shape.shoulder_span, 4),
                    "hip_span": round(self._user_shape.hip_span, 4),
                }
            return d

    # ── Vision-thread hooks ────────────────────────────────────────────────
    @property
    def is_frozen(self) -> bool:
        return self._state == "frozen" and self._frozen is not None

    def frozen_result(self) -> Optional["FrameResult"]:
        # Refresh timestamp & calibration so the FE sees a live heartbeat.
        if self._frozen is None:
            return None
        return self._frozen

    def tick(
        self,
        body_landmarks: list[dict],
        face_landmarks: list[dict],
        head_pose: Optional["HeadPose"],
        overlay: np.ndarray,
        clean_frame: np.ndarray,
        calibration: dict,
    ) -> None:
        """Update state and draw countdown/analyzing text onto `overlay` in place."""
        with self._lock:
            state = self._state
            t0 = self._t0

        now = time.time()
        if state in ("idle", "frozen", "fitting"):
            return

        if state == "countdown":
            remaining = _COUNTDOWN_SECONDS - (now - t0)
            if remaining <= 0:
                with self._lock:
                    self._state = "collecting"
                    self._t0 = now
                    self._buffer.clear()
                self._draw_centered_text(overlay, "GET READY", scale=1.2, color=(0, 220, 255))
            else:
                digit = int(math.ceil(remaining))
                self._draw_centered_text(overlay, str(digit), scale=6.0, color=(0, 255, 255), thickness=12)
            return

        if state == "collecting":
            elapsed = now - t0
            if _is_valid_skel_frame(body_landmarks):
                self._buffer.append(_BufferEntry(
                    body_landmarks=list(body_landmarks),
                    face_landmarks=list(face_landmarks),
                    head_pose=head_pose,
                    clean_bgr=clean_frame.copy(),
                ))
            if elapsed >= _COLLECT_SECONDS:
                self._finalize(calibration)

    # ── Internal helpers ───────────────────────────────────────────────────
    def _finalize(self, calibration: dict) -> None:
        with self._lock:
            buf = list(self._buffer)

        if not buf:
            # No valid frames captured (no person, occluded, etc.) — bail back to idle.
            with self._lock:
                self._state = "idle"
                self._buffer.clear()
            return

        lm_frames = [e.body_landmarks for e in buf]
        idx = _most_stable_index(lm_frames)
        chosen = buf[idx]

        # ── SMPL β fit (Phase 2). Runs in this vision thread; skipped silently
        # if weights are missing or torch/smplx isn't installed. The user is
        # holding still, so blocking for ~1–2 s here is acceptable.
        fitted_shape: Optional[UserShape] = None
        if self._fit_hook is not None:
            with self._lock:
                self._state = "fitting"
            t_start = time.time()
            try:
                fitted_shape = self._fit_hook(lm_frames)
                if fitted_shape is not None:
                    _SMPL_FIT_LOG.info(
                        "SMPL shape fit completed in %.2fs: upper_arm=%.3fm forearm=%.3fm",
                        time.time() - t_start,
                        fitted_shape.upper_arm_len,
                        fitted_shape.forearm_len,
                    )
            except Exception as e:
                _SMPL_FIT_LOG.warning("SMPL fit failed (%s); proceeding without shape", e)

        # Re-render the chosen frame: skeleton overlay + STABLE badge.
        frozen_overlay = chosen.clean_bgr.copy()
        _draw_skeleton_from_dicts(frozen_overlay, chosen.body_landmarks)
        h, w = frozen_overlay.shape[:2]
        cv2.rectangle(frozen_overlay, (0, 0), (w, 40), (0, 100, 0), -1)
        cv2.putText(
            frozen_overlay, "STABLE POSITION CAPTURED",
            (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2,
        )
        ok, jpeg = cv2.imencode(".jpg", frozen_overlay, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            with self._lock:
                self._state = "idle"
                self._buffer.clear()
            return

        frozen = FrameResult(
            body_landmarks=chosen.body_landmarks,
            face_landmarks=chosen.face_landmarks,
            head_pose=chosen.head_pose,
            jpeg_bytes=jpeg.tobytes(),
            calibration=calibration,
            clean_frame=chosen.clean_bgr,
        )

        with self._lock:
            self._frozen = frozen
            self._user_shape = fitted_shape
            self._state = "frozen"
            self._buffer.clear()

    @staticmethod
    def _draw_centered_text(img: np.ndarray, text: str, scale: float, color: tuple, thickness: int = 4) -> None:
        h, w = img.shape[:2]
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
        x = (w - tw) // 2
        y = (h + th) // 2
        # Dark outline for legibility
        cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thickness + 4)
        cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness)


def _draw_skeleton_from_dicts(frame: np.ndarray, landmarks: list[dict]) -> None:
    """Draw skeleton overlay from dict-format landmarks (frozen-frame replay path)."""
    h, w = frame.shape[:2]
    pts = [(int(lm["x"] * w), int(lm["y"] * h)) for lm in landmarks]
    vis = [lm.get("visibility", 0.0) for lm in landmarks]

    for a, b in _POSE_CONNECTIONS:
        if a >= len(pts) or b >= len(pts):
            continue
        if vis[a] < 0.2 or vis[b] < 0.2:
            continue
        alpha = max(0.2, (vis[a] + vis[b]) / 2)
        color = (int(120 * alpha), int(180 * alpha), int(255 * alpha))
        cv2.line(frame, pts[a], pts[b], color, 2)

    for i, (px, py) in enumerate(pts):
        if vis[i] < 0.2:
            continue
        if i in (_NOSE_IDX, _LEFT_EAR_IDX, _RIGHT_EAR_IDX):
            cv2.circle(frame, (px, py), 8, (255, 0, 255), -1)
            cv2.circle(frame, (px, py), 8, (255, 255, 255), 1)
        else:
            v = vis[i]
            if v > 0.8:
                color = (0, 255, 136)
            elif v > 0.4:
                color = (0, 204, 255)
            else:
                color = (0, 68, 255)
            cv2.circle(frame, (px, py), 5, color, -1)


def _default_smpl_fit_hook(frames: list[list[dict]]) -> Optional[UserShape]:
    """Run the SMPL β fit, swallowing common opt-in failures.

    Missing weights or absent torch/smplx is a normal state for fresh checkouts
    — log it once and proceed without per-person shape. Any other exception
    propagates so ``StabilityCapture._finalize`` can record a clear warning.
    """
    try:
        from .smpl_fit import fit_betas
        from .smpl_loader import SMPLWeightsMissingError
    except ImportError as e:
        _SMPL_FIT_LOG.info("SMPL stack not installed (%s); shape calibration skipped", e)
        return None
    try:
        return fit_betas(frames)
    except SMPLWeightsMissingError as e:
        _SMPL_FIT_LOG.info("%s", e)
        return None


class PoseEstimator:
    def __init__(self, camera_index: int = 0, target_fps: float = 30.0):
        self._camera_index = camera_index
        self._target_fps = target_fps
        self._cap: Optional[cv2.VideoCapture] = None
        self._pose_detector: Optional[mp_vision.PoseLandmarker] = None
        self._face_detector: Optional[mp_vision.FaceLandmarker] = None
        self.calibration = CalibrationManager()
        self._yaw_f = OneEuroFilter(min_cutoff=1.0, beta=0.1)
        self._pitch_f = OneEuroFilter(min_cutoff=1.0, beta=0.1)
        self._roll_f = OneEuroFilter(min_cutoff=1.0, beta=0.1)
        # Parallel filters for the world-landmark head pose path, kept separate
        # so PnP↔world source switches don't pollute filter state.
        self._yaw_w_f = OneEuroFilter(min_cutoff=1.0, beta=0.1)
        self._pitch_w_f = OneEuroFilter(min_cutoff=1.0, beta=0.1)
        self._roll_w_f = OneEuroFilter(min_cutoff=1.0, beta=0.1)
        # Per-landmark filters for image-normalized coords (used for overlay /
        # stability metric / frontend rendering).
        self._lm_filters: list[list[OneEuroFilter]] = [
            [OneEuroFilter(min_cutoff=0.5, beta=0.05) for _ in range(3)]
            for _ in range(33)
        ]
        # Per-landmark filters for world coords (meters, hip-centered) — these
        # feed the joint-angle math in pose_to_robot. Need their own state.
        self._lm_world_filters: list[list[OneEuroFilter]] = [
            [OneEuroFilter(min_cutoff=0.5, beta=0.05) for _ in range(3)]
            for _ in range(33)
        ]
        self._pnp_fail_count = 0
        self._frame_width = 640
        self._frame_height = 480
        self._running = False
        self.stability = StabilityCapture(fit_hook=_default_smpl_fit_hook)

    @property
    def user_shape(self) -> Optional[UserShape]:
        """The SMPL β fit produced by the most recent stable-pose capture, if any."""
        return self.stability.user_shape

    def open(self):
        import logging as _log
        log = _log.getLogger("vision")

        pose_model = _MODELS_DIR / "pose_landmarker_lite.task"
        face_model = _MODELS_DIR / "face_landmarker.task"
        log.info("Checking/downloading models...")
        _download_model(_POSE_MODEL_URL, pose_model)
        _download_model(_FACE_MODEL_URL, face_model)
        log.info("Models ready")

        log.info("Loading pose landmarker...")
        pose_opts = mp_vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(pose_model)),
            running_mode=mp_vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._pose_detector = mp_vision.PoseLandmarker.create_from_options(pose_opts)
        log.info("Pose landmarker loaded")

        log.info("Loading face landmarker...")
        face_opts = mp_vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(face_model)),
            running_mode=mp_vision.RunningMode.IMAGE,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
        )
        self._face_detector = mp_vision.FaceLandmarker.create_from_options(face_opts)
        log.info("Face landmarker loaded")

        log.info("Opening camera %d...", self._camera_index)
        self._cap = cv2.VideoCapture(self._camera_index)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self._cap.set(cv2.CAP_PROP_FPS, self._target_fps)
        self._frame_width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._frame_height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        log.info("Camera ready at %dx%d", self._frame_width, self._frame_height)
        self._running = True

    def close(self):
        self._running = False
        if self._cap:
            self._cap.release()
            self._cap = None
        if self._pose_detector:
            self._pose_detector.close()
            self._pose_detector = None
        if self._face_detector:
            self._face_detector.close()
            self._face_detector = None

    @property
    def is_running(self) -> bool:
        return self._running

    def _camera_matrix(self) -> np.ndarray:
        fx = fy = float(self._frame_width)
        cx = self._frame_width / 2.0
        cy = self._frame_height / 2.0
        return np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)

    @staticmethod
    def _world_head_pose(body_landmarks: list[dict]) -> Optional[tuple[float, float, float]]:
        """Compute (yaw_deg, pitch_deg, roll_deg) torso-relative from world coords.

        Returns None if any required landmark is missing world coords or has
        visibility below 0.5. yaw>0 = looking person's right, pitch>0 = up,
        roll>0 = head tilted to person's right.
        """
        required = (
            geometry.NOSE,
            geometry.LEFT_EAR,
            geometry.RIGHT_EAR,
            geometry.LEFT_SHOULDER,
            geometry.RIGHT_SHOULDER,
            geometry.LEFT_HIP,
            geometry.RIGHT_HIP,
        )
        if len(body_landmarks) <= max(required):
            return None
        for idx in required:
            lm = body_landmarks[idx]
            if "xw" not in lm or lm.get("visibility", 0.0) < 0.5:
                return None

        R = geometry.torso_frame(
            geometry.world_xyz(body_landmarks[geometry.LEFT_SHOULDER]),
            geometry.world_xyz(body_landmarks[geometry.RIGHT_SHOULDER]),
            geometry.world_xyz(body_landmarks[geometry.LEFT_HIP]),
            geometry.world_xyz(body_landmarks[geometry.RIGHT_HIP]),
        )
        pan, tilt, roll = geometry.head_pan_tilt_roll(
            geometry.world_xyz(body_landmarks[geometry.NOSE]),
            geometry.world_xyz(body_landmarks[geometry.LEFT_EAR]),
            geometry.world_xyz(body_landmarks[geometry.RIGHT_EAR]),
            R,
        )
        return math.degrees(pan), math.degrees(tilt), math.degrees(roll)

    def _solve_pnp(
        self, face_landmarks: list
    ) -> Optional[tuple]:
        """Returns (raw_yaw, raw_pitch, raw_roll, rvec, tvec) or None."""
        if len(face_landmarks) < max(_FACE_LM_INDICES) + 1:
            return None

        pts_2d = np.array(
            [
                [face_landmarks[i].x * self._frame_width,
                 face_landmarks[i].y * self._frame_height]
                for i in _FACE_LM_INDICES
            ],
            dtype=np.float64,
        )

        cam_matrix = self._camera_matrix()
        dist_coeffs = np.zeros((4, 1), dtype=np.float64)

        success, rvec, tvec = cv2.solvePnP(
            _HEAD_3D_POINTS,
            pts_2d,
            cam_matrix,
            dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not success:
            return None

        rot_mat, _ = cv2.Rodrigues(rvec)
        proj_matrix = np.hstack((rot_mat, tvec))
        _, _, _, _, _, _, euler = cv2.decomposeProjectionMatrix(proj_matrix)
        euler = euler.flatten()
        pitch = float(euler[0])
        yaw = float(euler[1])
        roll = float(euler[2])
        return yaw, pitch, roll, rvec, tvec

    def process_frame(self) -> Optional[FrameResult]:
        if not self._cap or not self._pose_detector or not self._face_detector:
            return None

        ret, frame = self._cap.read()
        if not ret:
            return None

        if self.stability.is_frozen:
            frozen = self.stability.frozen_result()
            if frozen is not None:
                return frozen

        clean_frame = frame.copy()
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        pose_result = self._pose_detector.detect(mp_image)
        face_result = self._face_detector.detect(mp_image)

        overlay = frame.copy()

        # Draw body skeleton
        body_landmarks: list[dict] = []
        raw_pose_lms = None
        if pose_result.pose_landmarks:
            raw_pose_lms = pose_result.pose_landmarks[0]
            world_lms = (
                pose_result.pose_world_landmarks[0]
                if pose_result.pose_world_landmarks
                else None
            )
            t_lm = time.time()
            for i, lm in enumerate(raw_pose_lms):
                fx = self._lm_filters[i][0].filter(lm.x, t_lm)
                fy = self._lm_filters[i][1].filter(lm.y, t_lm)
                fz = self._lm_filters[i][2].filter(lm.z, t_lm)
                entry = {
                    "x": round(fx, 4),
                    "y": round(fy, 4),
                    "z": round(fz, 4),
                    "visibility": round(lm.visibility or 0.0, 3),
                }
                if world_lms is not None and i < len(world_lms):
                    wlm = world_lms[i]
                    fxw = self._lm_world_filters[i][0].filter(wlm.x, t_lm)
                    fyw = self._lm_world_filters[i][1].filter(wlm.y, t_lm)
                    fzw = self._lm_world_filters[i][2].filter(wlm.z, t_lm)
                    entry["xw"] = round(fxw, 5)
                    entry["yw"] = round(fyw, 5)
                    entry["zw"] = round(fzw, 5)
                body_landmarks.append(entry)
            self._draw_pose_skeleton(overlay, raw_pose_lms)

        # Solve head pose: prefer torso-relative from world landmarks (decouples
        # head from torso rotation); fall back to face-PnP when shoulders/hips
        # are not visible.
        head_pose: Optional[HeadPose] = None
        face_landmarks_out: list[dict] = []
        raw_face_lms = None
        t_now = time.time()

        world_head = self._world_head_pose(body_landmarks)
        if world_head is not None:
            self._pnp_fail_count = 0
            raw_yaw, raw_pitch, raw_roll = world_head
            raw_yaw = self._yaw_w_f.filter(raw_yaw, t_now)
            raw_pitch = self._pitch_w_f.filter(raw_pitch, t_now)
            raw_roll = self._roll_w_f.filter(raw_roll, t_now)
            if self.calibration.state == CalibrationState.COLLECTING:
                self.calibration.add_frame(raw_yaw, raw_pitch, raw_roll)
            yaw, pitch, roll = self.calibration.apply(raw_yaw, raw_pitch, raw_roll)
            head_pose = HeadPose(yaw, pitch, roll, raw_yaw, raw_pitch, raw_roll)

        if face_result.face_landmarks:
            raw_face_lms = face_result.face_landmarks[0]
            pnp_result = self._solve_pnp(raw_face_lms)
            if pnp_result is not None:
                raw_yaw_p, raw_pitch_p, raw_roll_p, rvec, tvec = pnp_result

                raw_yaw_p = self._yaw_f.filter(raw_yaw_p, t_now)
                raw_pitch_p = self._pitch_f.filter(raw_pitch_p, t_now)
                raw_roll_p = self._roll_f.filter(raw_roll_p, t_now)

                # Use PnP only when the world-landmark path wasn't available.
                if head_pose is None:
                    self._pnp_fail_count = 0
                    if self.calibration.state == CalibrationState.COLLECTING:
                        self.calibration.add_frame(raw_yaw_p, raw_pitch_p, raw_roll_p)
                    yaw, pitch, roll = self.calibration.apply(raw_yaw_p, raw_pitch_p, raw_roll_p)
                    head_pose = HeadPose(yaw, pitch, roll, raw_yaw_p, raw_pitch_p, raw_roll_p)

                # Extract face landmark data and draw (always, for overlay/FE)
                for idx, name in zip(_FACE_LM_INDICES, _FACE_LM_NAMES):
                    lm = raw_face_lms[idx]
                    px = int(lm.x * self._frame_width)
                    py = int(lm.y * self._frame_height)
                    cv2.circle(overlay, (px, py), 6, (255, 0, 255), -1)
                    face_landmarks_out.append({
                        "index": idx,
                        "name": name,
                        "x": round(lm.x, 4),
                        "y": round(lm.y, 4),
                    })

                # Draw 3D orientation axes (PnP-derived, for visualization only)
                cam_matrix = self._camera_matrix()
                dist_coeffs = np.zeros((4, 1), dtype=np.float64)
                axis_pts = np.float32([[50, 0, 0], [0, 50, 0], [0, 0, -50], [0, 0, 0]])
                proj_pts, _ = cv2.projectPoints(axis_pts, rvec, tvec, cam_matrix, dist_coeffs)
                origin = tuple(proj_pts[3].ravel().astype(int))
                def clamp_pt(pt):
                    x = int(np.clip(pt[0], -5000, 5000))
                    y = int(np.clip(pt[1], -5000, 5000))
                    return (x, y)
                cv2.arrowedLine(overlay, origin, clamp_pt(proj_pts[0].ravel()), (0, 0, 255), 2, tipLength=0.3)
                cv2.arrowedLine(overlay, origin, clamp_pt(proj_pts[1].ravel()), (0, 255, 0), 2, tipLength=0.3)
                cv2.arrowedLine(overlay, origin, clamp_pt(proj_pts[2].ravel()), (255, 0, 0), 2, tipLength=0.3)
            elif head_pose is None:
                self._pnp_fail_count += 1
        elif head_pose is None:
            self._pnp_fail_count += 1

        cal = self.calibration.to_dict()

        self.stability.tick(
            body_landmarks=body_landmarks,
            face_landmarks=face_landmarks_out,
            head_pose=head_pose,
            overlay=overlay,
            clean_frame=clean_frame,
            calibration=cal,
        )
        if self.stability.is_frozen:
            frozen = self.stability.frozen_result()
            if frozen is not None:
                return frozen

        _, jpeg = cv2.imencode(".jpg", overlay, [cv2.IMWRITE_JPEG_QUALITY, 70])

        return FrameResult(
            body_landmarks=body_landmarks,
            face_landmarks=face_landmarks_out,
            head_pose=head_pose,
            jpeg_bytes=jpeg.tobytes(),
            calibration=cal,
            clean_frame=clean_frame,
        )

    def _draw_pose_skeleton(self, frame: np.ndarray, landmarks: list):
        h, w = frame.shape[:2]
        pts = [(int(lm.x * w), int(lm.y * h)) for lm in landmarks]
        vis = [lm.visibility or 0.0 for lm in landmarks]

        for a, b in _POSE_CONNECTIONS:
            if a >= len(pts) or b >= len(pts):
                continue
            if vis[a] < 0.2 or vis[b] < 0.2:
                continue
            alpha = max(0.2, (vis[a] + vis[b]) / 2)
            color = (int(120 * alpha), int(180 * alpha), int(255 * alpha))
            cv2.line(frame, pts[a], pts[b], color, 2)

        for i, (px, py) in enumerate(pts):
            if vis[i] < 0.2:
                continue
            if i in (_NOSE_IDX, _LEFT_EAR_IDX, _RIGHT_EAR_IDX):
                cv2.circle(frame, (px, py), 8, (255, 0, 255), -1)
                cv2.circle(frame, (px, py), 8, (255, 255, 255), 1)
            else:
                v = vis[i]
                if v > 0.8:
                    color = (0, 255, 136)
                elif v > 0.4:
                    color = (0, 204, 255)
                else:
                    color = (0, 68, 255)
                cv2.circle(frame, (px, py), 5, color, -1)

    @property
    def pnp_fail_count(self) -> int:
        return self._pnp_fail_count
