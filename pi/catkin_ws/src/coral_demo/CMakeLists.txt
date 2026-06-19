cmake_minimum_required(VERSION 3.0.2)
project(coral_demo)

find_package(catkin REQUIRED COMPONENTS
  rospy
  std_msgs
  sensor_msgs
  message_generation
)

add_service_files(
  FILES
  ClassifyFrame.srv
  WatchForGesture.srv
  ExecuteBody.srv
  Speak.srv
  AudioToAction.srv
)

generate_messages(
  DEPENDENCIES
  std_msgs
  sensor_msgs
)

catkin_package(
  CATKIN_DEPENDS rospy std_msgs sensor_msgs message_runtime
)

catkin_install_python(PROGRAMS
  scripts/vision_node.py
  scripts/head_node.py
  scripts/body_node.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)
