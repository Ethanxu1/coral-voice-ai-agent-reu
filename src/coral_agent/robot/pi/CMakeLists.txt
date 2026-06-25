cmake_minimum_required(VERSION 3.0.2)
project(ainex_demo)

# The catkin project name (ainex_demo) is what the generated Python service
# module is named, so it MUST match the imports in the nodes:
#   from ainex_demo.srv import BodyCommand, BodyCommandResponse

find_package(catkin REQUIRED COMPONENTS
  rospy
  std_msgs
  sensor_msgs
  message_generation
)

## ── Services ────────────────────────────────────────────────────────────────
## Looks in this package's srv/ directory by default.
add_service_files(
  FILES
    BodyCommand.srv
)

generate_messages(
  DEPENDENCIES
    std_msgs
)

catkin_package(
  CATKIN_DEPENDS rospy std_msgs sensor_msgs message_runtime
)

include_directories(
  ${catkin_INCLUDE_DIRS}
)

## ── Install node scripts so roslaunch/rosrun can find them by basename ────────
## (ainex_demo.launch uses type="body.py", etc.) Each script needs a
## `#!/usr/bin/env python3` shebang and the executable bit (chmod +x nodes/*.py).
catkin_install_python(PROGRAMS
  nodes/vision.py
  nodes/head.py
  nodes/body.py
  nodes/robot_server.py
  nodes/motions.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)
