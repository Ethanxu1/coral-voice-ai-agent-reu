"""Hardware controller — sends servo commands to the robot over HTTP.

Runs on the laptop. The physical robot must be running robot_server.py, reachable
at ROBOT_IP:ROBOT_AGENT_PORT on the local network. The legacy /move, /stand,
/feedback and /positions endpoints it uses are preserved by robot_server.py.

Environment variables:
    ROBOT_IP          Robot's IP address (default: 192.168.8.219)
    ROBOT_AGENT_PORT  Robot agent HTTP port (default: 9000)
"""

import httpx
from loguru import logger

from app.config import ROBOT_AGENT_PORT, ROBOT_IP

from .hardware_angle_utils import sim_units_to_hardware_units, hardware_units_to_rad
from .interface import RobotController, ServoCommand, ServoFeedback
from .servo_config import JOINT_NAME_MAP, STAND_PULSE




class AiNexHardwareController(RobotController):
    """Sends servo commands to the physical robot via the robot agent HTTP API."""

    def __init__(
        self,
        robot_ip: str = ROBOT_IP,
        port: int = ROBOT_AGENT_PORT,
        timeout: float = 5.0,
    ):
        self._base = f"http://{robot_ip}:{port}"
        self._client = httpx.Client(timeout=timeout)
        logger.info(f"HardwareController → robot agent at {self._base}")
        self._verify_connection()

    def _verify_connection(self) -> None:
        try:
            r = self._client.get(f"{self._base}/health", timeout=3.0)
            if r.status_code == 200:
                logger.info("Robot agent reachable — connection OK")
            else:
                logger.warning(f"Robot agent returned HTTP {r.status_code}")
        except Exception as e:
            logger.warning(f"Could not reach robot agent at {self._base}: {e}")

    def send_commands(self, commands: list[ServoCommand]) -> None:
        """Convert sim servo units → hardware units and POST to robot agent."""
        payload = []
        for cmd in commands:
            joint_name = JOINT_NAME_MAP.get(cmd.servo_id)
            if joint_name is None:
                logger.warning(f"No joint name for servo ID {cmd.servo_id}")
                continue
            hw_pos = sim_units_to_hardware_units(cmd.position, joint_name)
            payload.append({
                "servo_id": cmd.servo_id,
                "position": hw_pos,
                "duration_ms": cmd.duration_ms,
            })
            logger.debug(
                f"servo {cmd.servo_id} ({joint_name}): "
                f"sim={cmd.position} → hw={hw_pos}  t={cmd.duration_ms}ms"
            )

        if not payload:
            return

        response = self._client.post(f"{self._base}/move", json=payload)
        response.raise_for_status()

    def read_feedback(self, servo_ids: list[int]) -> list[ServoFeedback]:
        """Request servo feedback from robot agent (temperature + voltage)."""
        try:
            r = self._client.post(
                f"{self._base}/feedback",
                json={"servo_ids": servo_ids},
                timeout=2.0,
            )
            if r.status_code == 200:
                data = r.json().get("feedback", [])
                return [
                    ServoFeedback(
                        servo_id=f["servo_id"],
                        position=f["position"],
                        temperature=f["temperature"],
                        voltage=f["voltage"],
                    )
                    for f in data
                ]
        except Exception as e:
            logger.debug(f"Feedback read failed: {e}")
        return []

    def reset_to_stand(self) -> None:
        """Tell robot agent to return all servos to stand pose."""
        try:
            self._client.post(f"{self._base}/stand", timeout=5.0)
            logger.info("Stand command sent to robot")
        except Exception as e:
            logger.error(f"Failed to send stand command: {e}")

    def get_joint_positions(self) -> dict[str, int]:
        """Return current hardware servo positions (0–1000 scale).

        Falls back to STAND_PULSE values if robot agent is unavailable.
        """
        try:
            r = self._client.get(f"{self._base}/positions", timeout=2.0)
            if r.status_code == 200:
                return r.json().get("positions", {})
        except Exception:
            pass
        return dict(STAND_PULSE)

    def get_joint_states(self) -> dict[str, float]:
        """Return current joint states as radians, matching simulator.get_all_joint_states() format."""
        hw_positions = self.get_joint_positions()
        states: dict[str, float] = {}
        for sid_str, hw_units in hw_positions.items():
            try:
                sid = int(sid_str)
            except (ValueError, TypeError):
                continue
            joint_name = JOINT_NAME_MAP.get(sid)
            if joint_name is None:
                continue
            states[joint_name] = hardware_units_to_rad(hw_units, joint_name)
        return states
