"""Shared rosbridge (roslibpy) connection helper for the Mac-side nodes.

The Mac can't run ROS1, so the director / audio / speaker connect to the
rosbridge_server running on the Pi over a WebSocket and behave like ROS nodes
(publish/subscribe topics, advertise/call services) through it.
"""
from __future__ import annotations

import os

import roslibpy
from dotenv import load_dotenv
from loguru import logger

load_dotenv()  # pick up OPENAI_API_KEY etc. for all Mac nodes

# Pi IP + rosbridge port (rosbridge_websocket default is 9090).
ROS_HOST = os.getenv("ROS_HOST", "192.168.8.219")
ROS_BRIDGE_PORT = int(os.getenv("ROS_BRIDGE_PORT", "9090"))

# Topic + service names shared across the Mac nodes and the frontend.
TOPIC_DEMO_STATE = "/demo_state"          # String(JSON): {state, ...} — UI
TOPIC_DEMO_COMMAND = "/demo/command"      # String(JSON): director -> frontend
TOPIC_AUDIO_RESULT = "/demo/audio_result"  # String(JSON): frontend -> director

SRV_SPEAK = "/speaker/speak"              # coral_demo/Speak       (Mac speaker)
SRV_AUDIO_TO_ACTION = "/audio/audio_to_action"  # coral_demo/AudioToAction (Mac audio)
SRV_CLASSIFY = "/vision_node/classify_frame"    # coral_demo/ClassifyFrame  (Pi)
SRV_WATCH_GESTURE = "/vision_node/watch_gesture"  # coral_demo/WatchForGesture (Pi)
SRV_EXECUTE_BODY = "/body_node/execute_body"     # coral_demo/ExecuteBody    (Pi)


def connect(host: str = ROS_HOST, port: int = ROS_BRIDGE_PORT) -> roslibpy.Ros:
    """Connect to the Pi's rosbridge and return the running client."""
    logger.info(f"Connecting to rosbridge at ws://{host}:{port}")
    client = roslibpy.Ros(host=host, port=port)
    client.run()
    logger.info("rosbridge connected" if client.is_connected else "rosbridge NOT connected")
    return client
