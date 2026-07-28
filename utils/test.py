import os
import cv2
import math
import time
import rospy
import signal
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from mediapipe.framework.formats import landmark_pb2
import ainex_sdk.fps as fps
from collections import deque
from sensor_msgs.msg import Image
from ainex_sdk.common import cv2_image2ros
from ainex_kinematics.motion_manager import MotionManager
from ainex_interfaces.srv import SetWalkingCommand

from datetime import datetime

from config import *

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

}

# All arm joints we control (10 servos, 5 per arm)

# in this case, we focus on using these specific arm joints for imitation
# i.e. using the head servo might be problematic for putting the person out of frame
ARM_JOINTS = [
    'l_sho_pitch', 'r_sho_pitch',
    'l_sho_roll',  'r_sho_roll',
    'l_el_pitch',  'r_el_pitch',
    'l_el_yaw',    'r_el_yaw',
    'l_gripper',   'r_gripper',
]

# Leg joints we control (12 servos, 6 per leg)

# we only use a limited number of the leg servos i believe, to keep the robot from tipping or falling over.

LEG_JOINTS = [
    'l_hip_yaw',   'r_hip_yaw',
    'l_hip_roll',  'r_hip_roll',
    'l_hip_pitch', 'r_hip_pitch',
    'l_knee',      'r_knee',
    'l_ank_pitch', 'r_ank_pitch',
    'l_ank_roll',  'r_ank_roll',
]

ALL_JOINTS = ARM_JOINTS + LEG_JOINTS


# In this case, we must define a ROS node because our demo_poses process must 
# communicate with other nodes (i.e. the default walking node)

class DemoPose():
    def __init__(self, name):

        rospy.init_node(name, anonymous=False)

        self.motion_manager = MotionManager()

        try:
            rospy.wait_for_service('walking/command', timeout=5)
            walk_cmd = rospy.ServiceProxy('walking/command', SetWalkingCommand)
            walk_cmd('stop')
            time.sleep(0.5)
            walk_cmd('disable')
            rospy.loginfo('[PoseMimic3D] walking module disabled')
        except Exception as e:
            rospy.logwarn('[PoseMimic3D] cannot connect walking service: %s' % str(e))


    def _execute_cmd(self, pulse):
        cmds = []
        for servo in SERVO_ID:
            cmds.append([SERVO_ID[servo], pulse[servo]])

            # motion manager is 1600 ms to complete the movement
        self.motion_manager.set_servos_position(1600, cmds)
        rospy.loginfo('[PoseMimic3D] stood'+str(datetime.now()))


    def run(self):
        self._execute_cmd(STAND_PULSE)
        time.sleep(2.0)
        self._execute_cmd(HANDS_UP_PULSE)
        time.sleep(2.0)


    
if __name__ == "__main__":
    import sys
    sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1)
    print("[MAIN] Starting demo_poses node (Tasks API)...", flush=True)
    try:
        node = DemoPose('pose_mimic')
        print("[MAIN] Node initialized, entering run loop", flush=True)
        node.run()
    except Exception as e:
        print("[MAIN] ERROR: %s" % e, flush=True)
        import traceback
        traceback.print_exc()