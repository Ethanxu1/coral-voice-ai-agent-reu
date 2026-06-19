#!/usr/bin/env python3
"""
Vision node — pose landmarks, live frames, pose classification & gesture watch.

Continuously reads the AiNex camera, runs MediaPipe PoseLandmarker, and streams:
  /stable_gest/landmarks        (String) per-frame landmarks JSON  (head_node uses this)
  /stable_gest/image_annotated  (Image)  skeleton-overlaid frame   (UI live feed)
  /stable_gest/image_clean      (Image)  un-annotated frame        (classification)

It also serves two blocking services for the Director:
  ~classify_frame   (coral_demo/ClassifyFrame)   classify the most-stable recent
                                                 clean frame into a pose class
  ~watch_gesture    (coral_demo/WatchForGesture) return once the subject performs
                                                 a progression gesture (hands close)

Subscribes: <ainex camera image topic> (from /camera param), /system/shutdown
"""
import os
import sys
import json
import time
import math
import threading
from collections import deque

import cv2
import rospy
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from mediapipe.framework.formats import landmark_pb2
from sensor_msgs.msg import Image
from std_msgs.msg import String, Bool
from ainex_sdk.common import cv2_image2ros

import torch
import torch.nn as nn
from torchvision import models, transforms
from PIL import Image as PILImage

from coral_demo.srv import (
    ClassifyFrame, ClassifyFrameResponse,
    WatchForGesture, WatchForGestureResponse,
)

SHUTDOWN_TOPIC = '/system/shutdown'

_PKG_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR  = os.path.join(_PKG_DIR, 'model')
LANDMARKER_PATH = os.path.join(MODEL_DIR, 'pose_landmarker_lite.task')
CLASSIFIER_PATH = os.path.join(MODEL_DIR, 'pose_classifier.pt')

# ── Stability scoring (Gaussian skeleton, from the old webserver) ─────────────
STABILITY_N        = 3
STABILITY_SIGMA    = 1.0
BUFFER_MAXLEN      = 45
REQUIRED_LANDMARKS = {11, 12, 13, 14, 15, 16}   # shoulders, elbows, wrists
PRESENCE_THRESH    = 0.4
VISIBILITY_THRESH  = 0.4

# ── Gesture (crossed / close hands) ───────────────────────────────────────────
CROSS_DIST_RATIO   = 0.8     # wrist distance / shoulder width below this = "close"
GESTURE_STREAK     = 3       # consecutive frames required to confirm

# ── Classifier preprocessing ──────────────────────────────────────────────────
_MEAN = [0.485, 0.456, 0.406]
_STD  = [0.229, 0.224, 0.225]
infer_tf = transforms.Compose([
    transforms.Resize(256),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize(_MEAN, _STD),
])


def _frame_distance(a, b):
    total = 0.0
    for la, lb in zip(a, b):
        dx, dy, dz = la['x'] - lb['x'], la['y'] - lb['y'], la['z'] - lb['z']
        total += math.sqrt(dx * dx + dy * dy + dz * dz)
    return total


def _stability_score(frames, idx, N, sigma):
    score = 0.0
    for k in range(-N, N + 1):
        if k == 0:
            continue
        j = idx + k
        if 0 <= j < len(frames):
            score += _frame_distance(frames[idx], frames[j]) * math.exp(-k * k / (2.0 * sigma * sigma))
    return score


def most_stable_frame(frames, N=STABILITY_N, sigma=STABILITY_SIGMA):
    if len(frames) < 2 * N + 1:
        return len(frames) // 2
    scores = [_stability_score(frames, i, N, sigma) for i in range(N, len(frames) - N)]
    return N + scores.index(min(scores))


def _lm_valid(norm_lm, idx):
    if idx >= len(norm_lm):
        return False
    lm = norm_lm[idx]
    return (lm.get('presence', 0) >= PRESENCE_THRESH and
            lm.get('visibility', 0) >= VISIBILITY_THRESH)


def _is_valid_skel_frame(norm_lm):
    return bool(norm_lm) and all(_lm_valid(norm_lm, i) for i in REQUIRED_LANDMARKS if i < len(norm_lm))


def load_classifier(model_path, device):
    checkpoint = torch.load(model_path, map_location=device)
    classes = checkpoint['classes']
    model = models.mobilenet_v3_large(weights=None)
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, len(classes))
    model.load_state_dict(checkpoint['state_dict'])
    model.to(device).eval()
    return model, classes


class VisionNode:
    def __init__(self):
        rospy.init_node('vision_node', anonymous=False)

        base_options = mp_python.BaseOptions(model_asset_path=LANDMARKER_PATH)
        self.detector = mp_vision.PoseLandmarker.create_from_options(
            mp_vision.PoseLandmarkerOptions(
                base_options=base_options,
                running_mode=mp_vision.RunningMode.IMAGE,
                num_poses=1,
                min_pose_detection_confidence=0.3,
                min_tracking_confidence=0.3,
            )
        )
        self.mp_pose = mp.solutions.pose
        self.mp_drawing = mp.solutions.drawing_utils

        self.device = (
            torch.device('cuda') if torch.cuda.is_available() else
            torch.device('cpu')
        )
        self.model, self.classes = load_classifier(CLASSIFIER_PATH, self.device)
        rospy.loginfo('[VisionNode] classifier loaded on %s — classes: %s',
                      self.device, self.classes)

        self._lock = threading.Lock()
        self.latest_image = None         # raw camera frame (RGB)
        self.latest_clean = None         # most recent clean BGR frame
        self.latest_lm    = None         # most recent landmark dicts (or None)
        self.buffer       = deque(maxlen=BUFFER_MAXLEN)  # (lm_dicts, clean_bgr)
        self.running      = True

        camera = rospy.get_param('/camera')
        rospy.Subscriber(
            '/{}/{}'.format(camera['camera_name'], camera['image_topic']),
            Image, self._image_cb,
        )

        self.annotated_pub = rospy.Publisher('/stable_gest/image_annotated', Image, queue_size=1)
        self.clean_pub     = rospy.Publisher('/stable_gest/image_clean', Image, queue_size=1)
        self.landmarks_pub = rospy.Publisher('/stable_gest/landmarks', String, queue_size=10)

        rospy.Service('~classify_frame', ClassifyFrame, self._handle_classify)
        rospy.Service('~watch_gesture', WatchForGesture, self._handle_watch)
        rospy.Subscriber(SHUTDOWN_TOPIC, Bool, self._shutdown_cb)
        rospy.loginfo('[VisionNode] ready — publishing /stable_gest/, services up')

    def _shutdown_cb(self, msg):
        if msg.data:
            rospy.logwarn('[VisionNode] kill received — shutting down')
            self.running = False
            rospy.signal_shutdown('kill command received')

    def _image_cb(self, ros_image):
        self.latest_image = np.ndarray(
            (ros_image.height, ros_image.width, 3),
            dtype=np.uint8, buffer=ros_image.data,
        )

    def _draw_landmarks(self, bgr, norm_lm):
        proto = landmark_pb2.NormalizedLandmarkList()
        proto.landmark.extend([
            landmark_pb2.NormalizedLandmark(x=lm.x, y=lm.y, z=lm.z) for lm in norm_lm
        ])
        self.mp_drawing.draw_landmarks(bgr, proto, self.mp_pose.POSE_CONNECTIONS)

    # ── classification ────────────────────────────────────────────────────────
    def classify_frame(self, bgr):
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        tensor = infer_tf(PILImage.fromarray(rgb)).unsqueeze(0).to(self.device)
        with torch.no_grad():
            probs = torch.softmax(self.model(tensor), dim=1)[0]
        conf, idx = probs.max(0)
        return self.classes[idx.item()], conf.item()

    def _handle_classify(self, req):
        with self._lock:
            buf = list(self.buffer)
        if not buf:
            rospy.logwarn('[VisionNode] classify requested but no human buffered')
            return ClassifyFrameResponse(move='', confidence=0.0, had_human=False, jpeg=b'')

        idx = most_stable_frame([b[0] for b in buf])
        _, frame = buf[idx]
        move, conf = self.classify_frame(frame)
        ok, enc = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        rospy.loginfo('[VisionNode] classified -> %s (%.1f%%)', move, conf * 100)
        return ClassifyFrameResponse(
            move=move, confidence=conf, had_human=True,
            jpeg=(enc.tobytes() if ok else b''),
        )

    # ── gesture watch ───────────────────────────────────────────────────────--
    def _hands_close(self, norm_lm):
        """True if wrists are close together relative to shoulder width.
        Easier/steadier to trigger than a true crossed-arms check (MediaPipe is
        too shaky for reliable cross detection)."""
        if not norm_lm or len(norm_lm) <= 16:
            return False
        l_sho, r_sho = norm_lm[11], norm_lm[12]
        l_wri, r_wri = norm_lm[15], norm_lm[16]

        sho_w = math.sqrt((l_sho['x'] - r_sho['x']) ** 2 + (l_sho['y'] - r_sho['y']) ** 2)
        wri_d = math.sqrt((l_wri['x'] - r_wri['x']) ** 2 + (l_wri['y'] - r_wri['y']) ** 2)
        if sho_w < 0.02:
            return False

        ratio = wri_d / sho_w
        close = ratio < CROSS_DIST_RATIO
        if int(time.time()) != getattr(self, '_cross_dbg_t', 0):
            self._cross_dbg_t = int(time.time())
            rospy.loginfo('[VisionNode] hands ratio=%.2f close=%s', ratio, close)
        return close

    def _handle_watch(self, req):
        deadline = None if req.timeout <= 0 else time.time() + req.timeout
        rate = rospy.Rate(10)
        streak = 0
        rospy.loginfo('[VisionNode] watching for gesture %r (timeout=%.1f)', req.gesture, req.timeout)
        while self.running and not rospy.is_shutdown():
            with self._lock:
                lm = self.latest_lm
            streak = streak + 1 if self._hands_close(lm) else 0
            if streak >= GESTURE_STREAK:
                rospy.loginfo('[VisionNode] gesture detected')
                return WatchForGestureResponse(detected=True)
            if deadline is not None and time.time() >= deadline:
                return WatchForGestureResponse(detected=False)
            rate.sleep()
        return WatchForGestureResponse(detected=False)

    # ── main detection loop ─────────────────────────────────────────────────--
    def run(self):
        rate = rospy.Rate(15)
        while self.running and not rospy.is_shutdown():
            if self.latest_image is None:
                rate.sleep()
                continue

            frame = cv2.flip(self.latest_image.copy(), 1)   # mirror
            self.latest_image = None

            result = self.detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=frame))
            bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            clean_bgr = bgr.copy()

            payload = {'timestamp': time.time(), 'norm_landmarks': [], 'world_landmarks': []}
            lm_dicts = None
            if result.pose_landmarks:
                norm_lm = result.pose_landmarks[0]
                self._draw_landmarks(bgr, norm_lm)
                lm_dicts = [
                    {'x': lm.x, 'y': lm.y, 'z': lm.z,
                     'presence': lm.presence, 'visibility': lm.visibility}
                    for lm in norm_lm
                ]
                payload['norm_landmarks'] = lm_dicts
            else:
                cv2.putText(bgr, 'no person', (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            with self._lock:
                self.latest_clean = clean_bgr
                self.latest_lm = lm_dicts
                if lm_dicts is not None and _is_valid_skel_frame(lm_dicts):
                    self.buffer.append((lm_dicts, clean_bgr.copy()))

            self.landmarks_pub.publish(String(data=json.dumps(payload)))
            self.annotated_pub.publish(cv2_image2ros(cv2.resize(bgr, (640, 480)), 'vision_node'))
            self.clean_pub.publish(cv2_image2ros(cv2.resize(clean_bgr, (640, 480)), 'vision_node'))
            rate.sleep()

        self.detector.close()
        rospy.signal_shutdown('done')


if __name__ == '__main__':
    sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1)
    print('[VisionNode] starting...', flush=True)
    try:
        VisionNode().run()
    except Exception as e:
        print('[VisionNode] ERROR: %s' % e, flush=True)
        import traceback
        traceback.print_exc()
