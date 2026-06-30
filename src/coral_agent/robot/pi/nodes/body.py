#!/usr/bin/env python3
"""Body node — pose actuation via the ``/body_commands`` service.

Previously a topic subscriber that mapped a class name to a hard-coded pose; now
a generic, blocking ROS **service**. ``robot_server.py`` sends a sequence of
``(pulse_dict, duration_ms)`` frames (JSON-encoded) and the service plays them
through the ``MotionManager`` one at a time, sleeping each frame's duration so
motor commands never overlap. It returns only after the whole sequence finishes —
that blocking return is what makes the HTTP ``/motion`` endpoint blocking.

An optional ``global_duration`` (ms) overrides every frame's duration, e.g. to
run a multi-frame motion at a single uniform speed.

Service:  /body_commands   (ainex_demo/BodyCommand)
Requires: the BodyCommand srv built in the ainex catkin workspace (see
          ../srv/BodyCommand.srv for the definition and build steps).
"""
import json
import time

import rospy
from std_msgs.msg import Bool

from ainex_kinematics.motion_manager import MotionManager
from ainex_demo.srv import BodyCommand, BodyCommandResponse  # type: ignore

# Topic the webserver broadcasts on to stop every node.
SHUTDOWN_TOPIC = '/system/shutdown'

# name → hardware servo ID. Head servos (23/24) are driven by the head node.
SERVO_ID = {
    'l_ank_roll': 1,   'r_ank_roll': 2,
    'l_ank_pitch': 3,  'r_ank_pitch': 4,
    'l_knee': 5,       'r_knee': 6,
    'l_hip_pitch': 7,  'r_hip_pitch': 8,
    'l_hip_roll': 9,   'r_hip_roll': 10,
    'l_hip_yaw': 11,   'r_hip_yaw': 12,
    'l_sho_pitch': 13, 'r_sho_pitch': 14,
    'l_sho_roll': 15,  'r_sho_roll': 16,
    'l_el_pitch': 17,  'r_el_pitch': 18,
    'l_el_yaw': 19,    'r_el_yaw': 20,
    'l_gripper': 21,   'r_gripper': 22,
    'head_pan': 23,    'head_tilt': 24,
}
EMPTY_SERVOS = {'head_pan', 'head_tilt'}

# Physical servo safety limits (override 0-1000 for constrained servos).
SERVO_LIMITS = {
    19: (0, 600),     # l_el_yaw
    20: (360, 850),   # r_el_yaw (damaged — never below 360)
}

MIN_FRAME_MS = 100  # floor for any single move duration


def _clamp(servo_id, position):
    lo, hi = SERVO_LIMITS.get(servo_id, (0, 1000))
    return max(lo, min(hi, int(position)))


def pulse_to_servos(pulse):
    """Convert {servo_name: pulse} into [[servo_id, safe_pulse], ...]."""
    servos = []
    for name, value in pulse.items():
        if name in EMPTY_SERVOS or value is None:
            continue
        sid = SERVO_ID.get(name)
        if sid is None or sid in (23, 24):
            continue
        servos.append([sid, _clamp(sid, value)])
    return servos


class BodyNode:
    def __init__(self):
        rospy.init_node('body_node', anonymous=False)
        self.motion_manager = MotionManager()

        rospy.Service('/body_commands', BodyCommand, self._handle_command)
        rospy.Subscriber(SHUTDOWN_TOPIC, Bool, self._shutdown_cb)

        # Start at the stand pose.
        self.motion_manager.set_servos_position(800, pulse_to_servos(_STAND_PULSE))
        rospy.loginfo('[BodyNode] ready — service /body_commands')

    def _shutdown_cb(self, msg):
        if msg.data:
            rospy.logwarn('[BodyNode] kill received — shutting down')
            rospy.signal_shutdown('kill command received')

    def _handle_command(self, req):
        """Play a JSON sequence of [pulse_dict, duration_ms] frames, blocking."""
        try:
            sequence = json.loads(req.commands_json)
        except (ValueError, TypeError) as e:
            rospy.logwarn('[BodyNode] bad commands_json: %s', e)
            return BodyCommandResponse(success=False, duration_ms=0.0)

        override = req.global_duration if req.global_duration and req.global_duration > 0 else None

        total_ms = 0.0
        for frame in sequence:
            try:
                pulse, duration = frame[0], frame[1]
            except (IndexError, TypeError):
                continue
            duration = max(MIN_FRAME_MS, int(override if override is not None else duration))
            servos = pulse_to_servos(pulse)
            if not servos:
                continue
            self.motion_manager.set_servos_position(duration, servos)

            # the 0.1 allows for error
            time.sleep((duration / 1000.0) + 0.1)  # block so the next frame doesn't overlap
            total_ms += duration

        rospy.loginfo('[BodyNode] played %d frames (%.0f ms)', len(sequence), total_ms)
        return BodyCommandResponse(success=True, duration_ms=total_ms)

    def run(self):
        rospy.spin()


# Stand pose (hardware pulses) — mirrors robot_control.STAND_PULSE.
_STAND_PULSE = {
    'l_ank_roll': 500,  'r_ank_roll': 500,
    'l_ank_pitch': 640, 'r_ank_pitch': 360,
    'l_knee': 500,      'r_knee': 500,
    'l_hip_pitch': 350, 'r_hip_pitch': 650,
    'l_hip_roll': 500,  'r_hip_roll': 500,
    'l_hip_yaw': 500,   'r_hip_yaw': 500,
    'l_sho_pitch': 835, 'r_sho_pitch': 165,
    'l_sho_roll': 830,  'r_sho_roll': 170,
    'l_el_pitch': 500,  'r_el_pitch': 500,
    'l_el_yaw': 150,    'r_el_yaw': 850,
    'l_gripper': 500,   'r_gripper': 500,
}


if __name__ == '__main__':
    import sys
    sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1)
    print('[BodyNode] starting...', flush=True)
    try:
        node = BodyNode()
        node.run()
    except Exception as e:
        print('[BodyNode] ERROR: %s' % e, flush=True)
        import traceback
        traceback.print_exc()
