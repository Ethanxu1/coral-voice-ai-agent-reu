#!/usr/bin/env python3
"""
Body node — pose actuation.

Subscribes to /body_commands (published by webserver.py at the end of every
classification cycle) and drives the body/arm servos into a hard-coded pose for
whichever of the 7 classes was detected.

The per-class servo targets are derived from the *_PULSE pose dicts in
config.py, converted into [[servo_id, position], ...] lists via
d6a_converter.pulse_to_servos (head servos are dropped — head.py drives those).

Subscribes: /body_commands
Publishes:  (none)
"""
import json
import time

import rospy
from std_msgs.msg import String, Bool
from ainex_kinematics.motion_manager import MotionManager

from config import (
    RESULTS_DURATION,
    T_POSE_PULSE,
    DAB_PULSE,
    SUPERHERO_PULSE,
    THINKER_PULSE,
    MUSCLES_PULSE,
    HANDS_UP_PULSE,
    WARRIOR_PULSE,
    STAND_PULSE,
)

# Topic the webserver broadcasts on to stop every node.
SHUTDOWN_TOPIC = '/system/shutdown'

# the id numbers that coorrespond to the names of each servo.
# roll refers to s
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

# Servos that live on the robot but are not stored in the .d6a file
# (the action files only cover Servo1..Servo22, the body and arms).
# These are emitted with a value of None so the pose dict can be filled in
# by hand later.
EMPTY_SERVOS = {'head_pan', 'head_tilt'}

def pulse_to_servos(pulse):
    """Convert a {servo_name: pulse} dict into [[servo_id, pulse], ...].

    Used to turn the *_PULSE pose dicts in config.py into the format
    MotionManager.set_servos_position expects. Head servos (and any None
    values) are skipped — the head is driven separately by head.py.
    """
    servos = []
    for name, value in pulse.items():
        if name in EMPTY_SERVOS or value is None:
            continue
        servos.append([SERVO_ID[name], value])
    return servos


# ── Tunable parameters ────────────────────────────────────────────────────────
MOVE_DURATION = 800    # ms passed to set_servos_position for body moves

# Per-class servo targets, built from the pulse poses in config.py.
# Each value is a list of [servo_id, position] pairs.
POSES = {
    't-pose':      pulse_to_servos(T_POSE_PULSE),
    'dab':         pulse_to_servos(DAB_PULSE),
    'superhero':   pulse_to_servos(SUPERHERO_PULSE),
    'thinker':     pulse_to_servos(THINKER_PULSE),
    'muscles':     pulse_to_servos(MUSCLES_PULSE),
    'hand-raised': pulse_to_servos(HANDS_UP_PULSE),
    'warrior2':    pulse_to_servos(WARRIOR_PULSE),
    'stand':       pulse_to_servos(STAND_PULSE)
}
# ─────────────────────────────────────────────────────────────────────────────


class BodyNode:
    def __init__(self):
        rospy.init_node('body_node', anonymous=False)

        self.motion_manager = MotionManager()

        rospy.Subscriber('/body_commands', String, self._command_cb)
        rospy.Subscriber(SHUTDOWN_TOPIC, Bool, self._shutdown_cb)
        rospy.loginfo('[BodyNode] ready — listening on /body_commands')

        # starts at stand position
        self.motion_manager.set_servos_position(MOVE_DURATION, POSES['stand'])

    def _shutdown_cb(self, msg):
        if msg.data:
            rospy.logwarn('[BodyNode] kill received — shutting down')
            rospy.signal_shutdown('kill command received')


    def _command_cb(self, msg):
        # Accept either a bare class name or a JSON payload {"move": "...", ...}.
        move = None
        try:
            payload = json.loads(msg.data)
            move = payload.get('move') if isinstance(payload, dict) else payload
        except (ValueError, TypeError):
            move = msg.data.strip()

        if move not in POSES:
            rospy.logwarn('[BodyNode] unknown move: %r', move)
            return

        servos = POSES[move]
        if not servos:
            rospy.loginfo('[BodyNode] move "%s" has no pose configured yet — skipping', move)
            return

        self.motion_manager.set_servos_position(MOVE_DURATION, servos)
        rospy.loginfo('[BodyNode] executed move "%s" (%d servos)', move, len(servos))

        # holds position for results screen duration seconds, then stands again
        time.sleep(RESULTS_DURATION)
        self.motion_manager.set_servos_position(MOVE_DURATION, POSES['stand'])

    def run(self):
        rospy.spin()


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
