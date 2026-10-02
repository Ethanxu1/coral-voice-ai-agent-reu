"""Hardware controller — sends servo commands to the robot over HTTP.

Runs on the laptop. The physical robot must be running robot_server.py, reachable
at ROBOT_IP:ROBOT_AGENT_PORT on the local network. The legacy /move, /stand,
/feedback and /positions endpoints it uses are preserved by robot_server.py.

Environment variables:
    ROBOT_IP          Robot's IP address (default: 192.168.8.219)
    ROBOT_AGENT_PORT  Robot agent HTTP port (default: 9000)
"""

import threading
import time

import httpx
from loguru import logger

from app.config import ROBOT_AGENT_PORT, ROBOT_IP

from .hardware_angle_utils import sim_units_to_hardware_units, hardware_units_to_rad
from .interface import RobotController, ServoCommand, ServoFeedback
from .servo_config import JOINT_NAME_MAP, STAND_PULSE

# Streamed move time = STREAM_GAP_STRETCH x the real gap since the previous
# send, within these bounds (ms). Over Wi-Fi the gap between sends was ~100 ms
# (median round trip 93 ms, worst 765 ms; 2026-10-02), so fixed 45 ms moves
# left the servos idle half the time -- move-stop jolts. Stretching each move
# to outlast the gap keeps them moving toward the newest target.
STREAM_GAP_STRETCH = 1.3
STREAM_MIN_MS = 60
STREAM_MAX_MS = 200


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
        # False once the robot has answered /stream with 404 (Pi code from
        # before /stream existed): stream_commands then uses blocking /move.
        self._stream_supported = True
        # Background stream sender: holds only the newest payload (latest
        # wins); see stream_commands.
        self._stream_cv = threading.Condition()
        self._stream_pending: list[dict] | None = None
        self._stream_busy = False
        self._stream_sender: threading.Thread | None = None
        self._last_stream_at: float | None = None
        self._last_stream_error_log = 0.0
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
        """Convert sim servo units → hardware units and POST to robot agent.
        Blocks until the robot has finished the motion.

        Streamed targets not yet sent are discarded first, and one already on
        the wire is allowed to land: otherwise a stale follow target could
        reach the robot AFTER this move (e.g. "back to stand") and undo it.
        """
        payload = self._payload(commands)
        if not payload:
            return
        with self._stream_cv:
            self._stream_pending = None
            while self._stream_busy:
                self._stream_cv.wait(1.0)

        response = self._client.post(f"{self._base}/move", json=payload)
        response.raise_for_status()

    def stream_commands(self, commands: list[ServoCommand]) -> None:
        """Hand targets to the robot without waiting -- for continuous streams.

        Returns at once. A background thread sends the NEWEST targets to the
        robot's /stream; any not yet sent are replaced (latest wins). Follow
        mode used to wait on each request, so Wi-Fi delays (median 93 ms,
        worst 765 ms, 2026-10-02) set its pace and every slow trip was a
        jerk. Each move's time is stretched to outlast the gap to the next
        send (STREAM_GAP_STRETCH), so the servos keep moving.
        """
        payload = self._payload(commands)
        if not payload:
            return
        with self._stream_cv:
            self._stream_pending = payload
            if self._stream_sender is None:
                self._stream_sender = threading.Thread(
                    target=self._stream_loop, name="hw-stream", daemon=True)
                self._stream_sender.start()
            self._stream_cv.notify_all()

    def flush_stream(self, timeout: float = 1.0) -> bool:
        """Wait until every streamed target has been sent. True if it was."""
        deadline = time.monotonic() + timeout
        with self._stream_cv:
            while self._stream_pending is not None or self._stream_busy:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._stream_cv.wait(left)
        return True

    def _stream_loop(self) -> None:
        while True:
            with self._stream_cv:
                while self._stream_pending is None:
                    self._stream_cv.wait()
                payload, self._stream_pending = self._stream_pending, None
                self._stream_busy = True
            try:
                self._send_stream(payload)
            except Exception as e:  # never let the sender thread die
                now = time.monotonic()
                if now - self._last_stream_error_log > 5.0:
                    logger.warning(f"Streaming to robot failed: {e}")
                    self._last_stream_error_log = now
            finally:
                with self._stream_cv:
                    self._stream_busy = False
                    self._stream_cv.notify_all()

    def _send_stream(self, payload: list[dict]) -> None:
        now = time.monotonic()
        if self._last_stream_at is None:
            duration = max(m["duration_ms"] for m in payload)
        else:
            duration = (now - self._last_stream_at) * 1000 * STREAM_GAP_STRETCH
        duration = int(min(STREAM_MAX_MS, max(STREAM_MIN_MS, duration)))
        self._last_stream_at = now
        payload = [{**m, "duration_ms": duration} for m in payload]

        if not self._stream_supported:
            self._client.post(f"{self._base}/move", json=payload).raise_for_status()
            return
        response = self._client.post(f"{self._base}/stream", json=payload, timeout=1.0)
        if response.status_code == 404:
            logger.warning("Robot has no /stream (old robot_server) — using blocking /move. "
                           "Deploy the current pi/nodes/server.py and body.py for smooth follow.")
            self._stream_supported = False
            self._client.post(f"{self._base}/move", json=payload).raise_for_status()
            return
        if response.status_code == 429:  # a blocking /move is playing; next frame is newer
            return
        response.raise_for_status()

    def _payload(self, commands: list[ServoCommand]) -> list[dict]:
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
        return payload

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
