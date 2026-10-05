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
Service:  /body_positions  (std_srvs/Trigger) -- the servos' ACTUAL positions,
          JSON {servo_id: pulse} in the reply message.
Topic:    /body_stream     (std_msgs/String) -- the same JSON frames, played
          at once with NO waiting, for continuous streams (follow mode). The
          server only publishes here while no /body_commands sequence is
          playing, so the two never overlap.
Requires: the BodyCommand srv built in the ainex catkin workspace (see
          ../srv/BodyCommand.srv for the definition and build steps).
"""
import json
import time

import rospy
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger, TriggerResponse

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

# set to none, we want all servos to move
EMPTY_SERVOS = {}

MIN_FRAME_MS = 100  # floor for any single move duration
MIN_STREAM_MS = 20  # floor for a /body_stream move (server.py MIN_STREAM_MS)
STREAM_TOPIC = '/body_stream'


# Servos read for /body_positions: legs and arms (head 23/24 is not fitted).
POSITION_IDS = list(range(1, 23))


def normalize_positions(raw, ids):
    """{servo_id: pulse} from whatever MotionManager.get_servos_position
    returns: a dict, [id, pos] pairs, or bare positions in `ids` order."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {int(k): int(v) for k, v in raw.items()}
    items = list(raw)
    if all(isinstance(x, (list, tuple)) and len(x) == 2 for x in items):
        return {int(i): int(p) for i, p in items}
    if len(items) == len(ids):
        return {int(i): int(p) for i, p in zip(ids, items)}
    raise ValueError("unrecognised get_servos_position result: %r" % (raw,))


def pulse_to_servos(pulse):
    """Convert {servo_name: pulse} into [[servo_id, pulse], ...].

    Deliberately NO safety clamp here: server.py already clamps every position
    to SERVO_LIMITS before it reaches this node, and a second clamp with its
    own copy of the table would silently fight the first whenever the two
    tables drift apart. server.py's table is the single hardware source of
    truth; this node just plays what it's given.
    """
    servos = []
    for name, value in pulse.items():
        if name in EMPTY_SERVOS or value is None:
            continue
        sid = SERVO_ID.get(name)
        if sid is None or sid in (23, 24):
            continue
        servos.append([sid, int(value)])
    return servos


class BodyNode:
    def __init__(self):
        rospy.init_node('body_node', anonymous=False)
        self.motion_manager = MotionManager()

        rospy.Service('/body_commands', BodyCommand, self._handle_command)
        rospy.Service('/body_positions', Trigger, self._handle_positions)
        # queue_size=1: only the newest target matters in a stream.
        rospy.Subscriber(STREAM_TOPIC, String, self._handle_stream, queue_size=1)
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

    def read_positions(self, ids):
        """Actual servo positions. The argument form of get_servos_position
        isn't documented here, so: a list of ids first, then one id at a
        time."""
        try:
            return normalize_positions(self.motion_manager.get_servos_position(ids), ids)
        except TypeError:
            out = {}
            for sid in ids:
                r = self.motion_manager.get_servos_position(sid)
                if isinstance(r, (list, tuple)):
                    out.update(normalize_positions([r] if len(r) == 2 and not isinstance(r[0], (list, tuple)) else r, [sid]))
                elif r is not None:
                    out[sid] = int(r)
            return out

    def _handle_positions(self, req):
        try:
            positions = self.read_positions(POSITION_IDS)
            return TriggerResponse(success=True, message=json.dumps(positions))
        except Exception as e:
            rospy.logwarn('[BodyNode] reading servo positions failed: %s', e)
            return TriggerResponse(success=False, message=str(e))

    def _handle_stream(self, msg):
        """Play stream frames immediately, without waiting for the motion.

        The servos glide to each target over its duration by themselves; the
        next frame (typically ~50 ms later) just replaces the target. Waiting
        here, as _handle_command does, is what made follow mode move-stop-move
        on the real robot (measured 2026-10-02).
        """
        try:
            frames = json.loads(msg.data)
        except (ValueError, TypeError) as e:
            rospy.logwarn('[BodyNode] bad stream frame: %s', e)
            return
        for frame in frames:
            try:
                pulse, duration = frame[0], frame[1]
            except (IndexError, TypeError, KeyError):
                continue
            servos = pulse_to_servos(pulse)
            if servos:
                self.motion_manager.set_servos_position(max(MIN_STREAM_MS, int(duration)), servos)

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
