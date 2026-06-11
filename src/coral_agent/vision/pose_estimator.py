from __future__ import annotations

import math
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from mediapipe.tasks.python.vision import drawing_utils as mp_drawing

from .calibration import CalibrationManager, CalibrationState

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

    def to_pose_dict(self) -> dict:
        return {
            "type": "pose_update",
            "timestamp": self.timestamp,
            "body_landmarks": self.body_landmarks,
            "face_landmarks": self.face_landmarks,
            "head_pose": self.head_pose.to_dict() if self.head_pose else None,
            "calibration": self.calibration,
        }


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
        # Per-landmark filters: 33 landmarks × 3 axes (x, y, z)
        self._lm_filters: list[list[OneEuroFilter]] = [
            [OneEuroFilter(min_cutoff=0.5, beta=0.05) for _ in range(3)]
            for _ in range(33)
        ]
        self._pnp_fail_count = 0
        self._frame_width = 640
        self._frame_height = 480
        self._running = False

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
            t_lm = time.time()
            for i, lm in enumerate(raw_pose_lms):
                fx = self._lm_filters[i][0].filter(lm.x, t_lm)
                fy = self._lm_filters[i][1].filter(lm.y, t_lm)
                fz = self._lm_filters[i][2].filter(lm.z, t_lm)
                body_landmarks.append({
                    "x": round(fx, 4),
                    "y": round(fy, 4),
                    "z": round(fz, 4),
                    "visibility": round(lm.visibility or 0.0, 3),
                })
            self._draw_pose_skeleton(overlay, raw_pose_lms)

        # Solve head pose
        head_pose: Optional[HeadPose] = None
        face_landmarks_out: list[dict] = []
        raw_face_lms = None

        if face_result.face_landmarks:
            raw_face_lms = face_result.face_landmarks[0]
            pnp_result = self._solve_pnp(raw_face_lms)
            if pnp_result is not None:
                self._pnp_fail_count = 0
                raw_yaw, raw_pitch, raw_roll, rvec, tvec = pnp_result

                t_now = time.time()
                raw_yaw = self._yaw_f.filter(raw_yaw, t_now)
                raw_pitch = self._pitch_f.filter(raw_pitch, t_now)
                raw_roll = self._roll_f.filter(raw_roll, t_now)

                if self.calibration.state == CalibrationState.COLLECTING:
                    self.calibration.add_frame(raw_yaw, raw_pitch, raw_roll)

                yaw, pitch, roll = self.calibration.apply(raw_yaw, raw_pitch, raw_roll)
                head_pose = HeadPose(yaw, pitch, roll, raw_yaw, raw_pitch, raw_roll)

                # Extract face landmark data and draw
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

                # Draw 3D orientation axes
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

                cv2.putText(overlay, f"Y:{yaw:.1f} P:{pitch:.1f} R:{roll:.1f}",
                            (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            else:
                self._pnp_fail_count += 1
        else:
            self._pnp_fail_count += 1

        cal = self.calibration.to_dict()
        cv2.putText(overlay, f"Cal: {cal['state']} {cal['progress']*100:.0f}%",
                    (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        _, jpeg = cv2.imencode(".jpg", overlay, [cv2.IMWRITE_JPEG_QUALITY, 70])

        return FrameResult(
            body_landmarks=body_landmarks,
            face_landmarks=face_landmarks_out,
            head_pose=head_pose,
            jpeg_bytes=jpeg.tobytes(),
            calibration=cal,
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
