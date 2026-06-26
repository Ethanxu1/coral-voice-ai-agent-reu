#!/usr/bin/env python3
"""Vision node — pose landmarks + frame streaming.

Subscribes to the AiNex camera, runs the MediaPipe PoseLandmarker on each frame,
and publishes:
    /annotated_frame  (sensor_msgs/Image)  — frame with landmarks drawn (livestream)
    /clean_frame      (sensor_msgs/Image)  — un-annotated frame (used by /classify)
    /landmarks        (std_msgs/String)    — JSON normalized + world landmarks

It also runs a tiny MJPEG HTTP server on port 9001 so the Mac frontend can pull
the annotated and clean streams directly over HTTP without a ROS bridge:
    GET /video_feed   annotated MJPEG stream
    GET /clean_feed   clean MJPEG stream

Subscribes: <camera>/<image_topic>
Publishes:  /annotated_frame, /clean_frame, /landmarks
"""
import os
import json
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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

# Topic the webserver broadcasts on to stop every node.
SHUTDOWN_TOPIC = '/system/shutdown'

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'model', 'pose_landmarker_lite.task')

STREAM_PORT = 9001


class _FrameStore:
    """Thread-safe holder for the latest annotated/clean JPEG bytes."""

    def __init__(self):
        self._lock = threading.Lock()
        self._annotated = None
        self._clean = None

    def set(self, annotated_jpeg, clean_jpeg):
        with self._lock:
            self._annotated = annotated_jpeg
            self._clean = clean_jpeg

    def get(self, kind):
        with self._lock:
            return self._annotated if kind == 'annotated' else self._clean


_FRAMES = _FrameStore()


class _MJPEGHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence per-request logging
        pass

    def do_GET(self):
        kind = {'/video_feed': 'annotated', '/clean_feed': 'clean'}.get(self.path)
        if kind is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        try:
            while True:
                jpeg = _FRAMES.get(kind)
                if jpeg is not None:
                    self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\n\r\n')
                    self.wfile.write(jpeg)
                    self.wfile.write(b'\r\n')
                time.sleep(1 / 30.0)
        except (BrokenPipeError, ConnectionResetError):
            pass


def _start_stream_server():
    server = ThreadingHTTPServer(('0.0.0.0', STREAM_PORT), _MJPEGHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print('[PosePublisher] MJPEG stream on :%d (/video_feed, /clean_feed)' % STREAM_PORT, flush=True)


class PosePublisher:
    def __init__(self):
        rospy.init_node('pose_publisher', anonymous=False)

        # IMAGE mode: no temporal smoothing — each frame independent.
        base_options = mp_python.BaseOptions(model_asset_path=MODEL_PATH)
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

        self.latest_image = None
        self.running = True

        camera = rospy.get_param('/camera')
        rospy.Subscriber(
            '/{}/{}'.format(camera['camera_name'], camera['image_topic']),
            Image, self._image_cb,
        )

        # Renamed pub/sub topics (pub/sub model).
        self.annotated_pub = rospy.Publisher('/annotated_frame', Image, queue_size=1)
        self.clean_pub = rospy.Publisher('/clean_frame', Image, queue_size=1)
        self.landmarks_pub = rospy.Publisher('/landmarks', String, queue_size=10)

        rospy.Subscriber(SHUTDOWN_TOPIC, Bool, self._shutdown_cb)

        _start_stream_server()
        rospy.loginfo('[PosePublisher] ready — publishing /annotated_frame, /clean_frame, /landmarks')

    def _shutdown_cb(self, msg):
        if msg.data:
            rospy.logwarn('[PosePublisher] kill received — shutting down')
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
            landmark_pb2.NormalizedLandmark(x=lm.x, y=lm.y, z=lm.z)
            for lm in norm_lm
        ])
        self.mp_drawing.draw_landmarks(bgr, proto, self.mp_pose.POSE_CONNECTIONS)

    def run(self):
        rate = rospy.Rate(15)
        self._frame_count = 0
        self._last_log = time.time()

        while self.running and not rospy.is_shutdown():
            if self.latest_image is None:
                rate.sleep()
                continue

            # Camera publishes RGB; flip horizontally for mirror effect.
            frame = cv2.flip(self.latest_image.copy(), 1)
            self.latest_image = None

            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
            result = self.detector.detect(mp_img)

            bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            clean_bgr = bgr.copy()   # snapshot before any landmark/text drawing

            payload = {
                'timestamp': time.time(),
                'norm_landmarks': [],
                'world_landmarks': [],
            }

            detected = result.pose_landmarks and result.pose_world_landmarks
            if detected:
                norm_lm = result.pose_landmarks[0]
                world_lm = result.pose_world_landmarks[0]

                self._draw_landmarks(bgr, norm_lm)

                payload['norm_landmarks'] = [
                    {'x': lm.x, 'y': lm.y, 'z': lm.z,
                     'presence': lm.presence, 'visibility': lm.visibility}
                    for lm in norm_lm
                ]
                payload['world_landmarks'] = [
                    {'x': lm.x, 'y': lm.y, 'z': lm.z,
                     'presence': lm.presence, 'visibility': lm.visibility}
                    for lm in world_lm
                ]
            else:
                cv2.putText(bgr, 'no person', (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            annotated = cv2.resize(bgr, (640, 480))
            clean = cv2.resize(clean_bgr, (640, 480))

            self.landmarks_pub.publish(String(data=json.dumps(payload)))
            self.annotated_pub.publish(cv2_image2ros(annotated, 'pose_publisher'))
            self.clean_pub.publish(cv2_image2ros(clean, 'pose_publisher'))

            # Feed the MJPEG stream server.
            ok_a, buf_a = cv2.imencode('.jpg', annotated)
            ok_c, buf_c = cv2.imencode('.jpg', clean)
            if ok_a and ok_c:
                _FRAMES.set(buf_a.tobytes(), buf_c.tobytes())

            self._frame_count += 1
            now = time.time()
            if now - self._last_log >= 1.0:
                status = 'person detected' if detected else 'no person'
                print('[PosePublisher] %d fps — %s' % (self._frame_count, status), flush=True)
                self._frame_count = 0
                self._last_log = now

            rate.sleep()

        self.detector.close()
        rospy.signal_shutdown('done')


if __name__ == '__main__':
    import sys
    sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1)
    print('[PosePublisher] starting...', flush=True)
    try:
        node = PosePublisher()
        node.run()
    except Exception as e:
        print('[PosePublisher] ERROR: %s' % e, flush=True)
        import traceback
        traceback.print_exc()
