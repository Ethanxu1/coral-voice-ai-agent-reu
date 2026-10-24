"""ROBOT_IP has no built-in default: hardware mode must refuse to start without it."""

import pytest

from app.robot.hardware_controller import AiNexHardwareController


@pytest.mark.parametrize("robot_ip", [None, ""])
def test_missing_robot_ip_raises(robot_ip):
    with pytest.raises(RuntimeError, match="ROBOT_IP"):
        AiNexHardwareController(robot_ip=robot_ip)
