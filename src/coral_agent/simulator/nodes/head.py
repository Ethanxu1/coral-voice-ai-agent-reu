#!/usr/bin/env python3
"""
Head node — subject tracking (quasi-IBVS).

Subscribes to /landmarks (published by the vision node) and nudges the
head pan/tilt servos to keep the midpoint between the shoulders centred in frame.

Safe servo ranges: pan [300, 700], tilt [400, 600].

Subscribes: /landmarks
Publishes:  (none)
"""
import json
import time
import threading

import rospy
from std_msgs.msg import String, Bool
from ainex_kinematics.motion_manager import MotionManager

# Topic the webserver broadcasts on to stop every node.
SHUTDOWN_TOPIC = '/system/shutdown'

# ── Tunable parameters ────────────────────────────────────────────────────────
UPDATE_EVERY  = 0.8    # seconds between head-move commands (must be > motor move time)
MOVE_DURATION = 600    # ms passed to set_servos_position for head moves
STEP          = 100    # servo units per unit of normalised image error (gain)

PAN_CENTER  = 500
TILT_CENTER = 500

PAN_MIN,  PAN_MAX  = 300, 700
TILT_MIN, TILT_MAX = 400, 600

# Servo IDs for head joints
HEAD_PAN_ID  = 23
HEAD_TILT_ID = 24

# Minimum per-landmark presence/visibility to accept a landmark
PRESENCE_THRESH    = 0.4
VISIBILITY_THRESH  = 0.4

# Landmark indices (MediaPipe BlazePose)
L_SHOULDER = 11
R_SHOULDER = 12
# ─────────────────────────────────────────────────────────────────────────────


def _lm_valid(norm_lm, idx):
    if idx >= len(norm_lm):
        return False
    lm = norm_lm[idx]
    return (lm.get('presence', 0) >= PRESENCE_THRESH and
            lm.get('visibility', 0) >= VISIBILITY_THRESH)


def _shoulder_midpoint(norm_lm):
    """Return the midpoint between both shoulders, or None if either is missing."""
    if not (_lm_valid(norm_lm, L_SHOULDER) and _lm_valid(norm_lm, R_SHOULDER)):
        return None
    ls = norm_lm[L_SHOULDER]
    rs = norm_lm[R_SHOULDER]
    return (ls['x'] + rs['x']) / 2.0, (ls['y'] + rs['y']) / 2.0


class HeadNode:
    def __init__(self):
        rospy.init_node('head_node', anonymous=False)

        self.motion_manager = MotionManager()

        self._lock        = threading.Lock()
        self._centers     = []           # (cx, cy) collected since last head move
        self._last_center = (0.5, 0.5)   # last average, used for fallback tiebreak
        self._cycle_start = time.time()

        self._pan  = PAN_CENTER
        self._tilt = TILT_CENTER

        # Move to centre on startup
        self.motion_manager.set_servos_position(
            MOVE_DURATION,
            [[HEAD_PAN_ID, self._pan], [HEAD_TILT_ID, self._tilt]],
        )

        rospy.Subscriber('/landmarks', String, self._landmarks_cb)
        rospy.Subscriber(SHUTDOWN_TOPIC, Bool, self._shutdown_cb)
        rospy.loginfo('[HeadNode] ready — update every %.2fs, step=%d', UPDATE_EVERY, STEP)

    def _shutdown_cb(self, msg):
        if msg.data:
            rospy.logwarn('[HeadNode] kill received — shutting down')
            rospy.signal_shutdown('kill command received')

    def _landmarks_cb(self, msg):
        try:
            payload = json.loads(msg.data)
        except Exception:
            return

        norm_lm = payload.get('norm_landmarks', [])
        center  = _shoulder_midpoint(norm_lm)

        with self._lock:
            now = time.time()
            if center is not None:
                self._centers.append(center)
            if now - self._cycle_start >= UPDATE_EVERY:
                self._update()
                self._centers     = []
                self._cycle_start = now

    def _update(self):
        """Compute average body center, derive error, nudge head. Called under lock."""
        if not self._centers:
            return

        avg_cx = sum(c[0] for c in self._centers) / len(self._centers)
        avg_cy = sum(c[1] for c in self._centers) / len(self._centers)
        self._last_center = (avg_cx, avg_cy)

        # Image center in normalised coords is (0.5, 0.5).
        # Positive horiz error → subject is to the right → pan should increase.
        # Positive vert error  → subject is below centre → tilt should decrease
        # (tilt value decreases as the head looks down on Ainex).
        horiz_err = avg_cx - 0.5
        vert_err  = avg_cy - 0.5

        new_pan  = int(self._pan  + STEP * horiz_err)
        new_tilt = int(self._tilt - STEP * vert_err)

        new_pan  = max(PAN_MIN,  min(PAN_MAX,  new_pan))
        new_tilt = max(TILT_MIN, min(TILT_MAX, new_tilt))

        if new_pan != self._pan or new_tilt != self._tilt:
            self.motion_manager.set_servos_position(
                MOVE_DURATION,
                [[HEAD_PAN_ID, new_pan], [HEAD_TILT_ID, new_tilt]],
            )
            rospy.loginfo(
                '[HeadNode] body=(%.3f,%.3f) err=(%.3f,%.3f) pan %d→%d tilt %d→%d',
                avg_cx, avg_cy, horiz_err, vert_err,
                self._pan, new_pan, self._tilt, new_tilt,
            )
            self._pan  = new_pan
            self._tilt = new_tilt

    def run(self):
        rospy.spin()


if __name__ == '__main__':
    import sys
    sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1)
    print('[HeadNode] starting...', flush=True)
    try:
        node = HeadNode()
        node.run()
    except Exception as e:
        print('[HeadNode] ERROR: %s' % e, flush=True)
        import traceback
        traceback.print_exc()
