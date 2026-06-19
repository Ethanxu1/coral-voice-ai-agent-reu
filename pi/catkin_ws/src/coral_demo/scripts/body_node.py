#!/usr/bin/env python3
"""
Body node — pose actuation as a BLOCKING service.

Exposes the ExecuteBody service: the call does not return until the motion has
finished (duration_ms has elapsed), which prevents the Director from sending
overlapping commands to the same servos.

Two request modes:
  * pose class  — `move` set to a known class (e.g. "t-pose", "stand"); looks up
                  the matching *_PULSE pose in poses.py.
  * explicit    — `move` empty + servo_ids/positions (voice "fix my pose" path,
                  already clamped to safe ranges on the Mac side).

Dev mode (~dev_mode param, default True): pose-class requests are forced to the
stand pose instead of the real pose, per the demo spec ("for development the
robot simply returns to / executes from stand"). Explicit joint targets still
execute so the voice path can be exercised.

Service:    ~execute_body   (coral_demo/ExecuteBody)
Subscribes: /system/shutdown
"""
import sys
import os

import rospy
from std_msgs.msg import Bool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poses  # noqa: E402  (sibling module: SERVO_ID, CLASS_TO_PULSE, helpers)

from coral_demo.srv import ExecuteBody, ExecuteBodyResponse  # noqa: E402

from ainex_kinematics.motion_manager import MotionManager  # noqa: E402

SHUTDOWN_TOPIC = '/system/shutdown'

DEFAULT_MOVE_DURATION = 800   # ms, when a request leaves duration_ms <= 0
HOLD_DURATION = poses.RESULTS_DURATION  # seconds to hold a pose before standing


class BodyNode:
    def __init__(self):
        rospy.init_node('body_node', anonymous=False)
        self.dev_mode = rospy.get_param('~dev_mode', True)
        self.motion_manager = MotionManager()

        # Stand on startup.
        self._move(poses.pulse_to_servos(poses.STAND_PULSE), DEFAULT_MOVE_DURATION)

        rospy.Service('~execute_body', ExecuteBody, self._handle_execute)
        rospy.Subscriber(SHUTDOWN_TOPIC, Bool, self._shutdown_cb)
        rospy.loginfo('[BodyNode] ready (dev_mode=%s) — service ~execute_body', self.dev_mode)

    def _shutdown_cb(self, msg):
        if msg.data:
            rospy.logwarn('[BodyNode] kill received — shutting down')
            rospy.signal_shutdown('kill command received')

    def _move(self, servos, duration_ms):
        """Send a servo batch and BLOCK until it should have finished."""
        if not servos:
            return
        self.motion_manager.set_servos_position(duration_ms, servos)
        rospy.sleep(duration_ms / 1000.0)

    def _resolve_servos(self, req):
        """Turn an ExecuteBody request into [[servo_id, pulse], ...]."""
        if req.move:
            pulse = poses.CLASS_TO_PULSE.get(req.move)
            if pulse is None:
                rospy.logwarn('[BodyNode] unknown move %r — using stand', req.move)
                pulse = poses.STAND_PULSE
            elif self.dev_mode:
                rospy.loginfo('[BodyNode] dev_mode — %r forced to stand', req.move)
                pulse = poses.STAND_PULSE
            return poses.pulse_to_servos(pulse)

        # explicit servo targets (voice path); clamp defensively.
        return [
            [int(sid), poses.clamp_pulse(int(sid), pos)]
            for sid, pos in zip(req.servo_ids, req.positions)
            if int(sid) not in (poses.SERVO_ID['head_pan'], poses.SERVO_ID['head_tilt'])
        ]

    def _handle_execute(self, req):
        duration = req.duration_ms if req.duration_ms > 0 else DEFAULT_MOVE_DURATION
        servos = self._resolve_servos(req)
        rospy.loginfo('[BodyNode] execute move=%r servos=%d dur=%dms',
                      req.move, len(servos), duration)

        self._move(servos, duration)

        if req.return_to_stand:
            rospy.sleep(HOLD_DURATION)
            self._move(poses.pulse_to_servos(poses.STAND_PULSE), DEFAULT_MOVE_DURATION)

        return ExecuteBodyResponse(done=True)

    def run(self):
        rospy.spin()


if __name__ == '__main__':
    sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1)
    print('[BodyNode] starting...', flush=True)
    try:
        BodyNode().run()
    except Exception as e:
        print('[BodyNode] ERROR: %s' % e, flush=True)
        import traceback
        traceback.print_exc()
