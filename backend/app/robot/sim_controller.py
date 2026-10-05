import threading
import time

from app.robot.angle_utils import rad_to_servo_units, servo_units_to_rad
from app.robot.hardware_controller import STREAM_GAP_STRETCH, STREAM_MAX_MS, STREAM_MIN_MS
from app.robot.interface import RobotController, ServoCommand, ServoFeedback
from app.robot.servo_config import JOINT_NAME_MAP, SERVO_ID_MAP


class SimController(RobotController):
    """RobotController backend that drives the MuJoCo simulator instead of hardware.

    Each servo command is executed in its own thread to simulate the parallel
    motion the physical bus achieves when moving multiple servos simultaneously.
    """

    # Streamed motion is stepped this often (s).
    STREAM_TICK = 0.01

    def __init__(self, simulator):
        self._sim = simulator
        # Streamed moves in progress: joint -> (start_rad, target_rad, t0, duration_s)
        self._moves: dict[str, tuple[float, float, float, float]] = {}
        self._moves_lock = threading.Lock()
        self._streamer: threading.Thread | None = None
        self._last_stream_at: float | None = None

    def send_commands(self, commands: list[ServoCommand]) -> None:
        """Dispatch servo commands to the MuJoCo simulator.

        Spawns one thread per command to simulate concurrent timed motion,
        mirroring how the physical bus processes multi-servo move commands.
        """
        threads = []
        with self._moves_lock:  # a blocking move owns its joints from here on
            for cmd in commands:
                self._moves.pop(JOINT_NAME_MAP.get(cmd.servo_id), None)
        for cmd in commands:
            joint_name = JOINT_NAME_MAP.get(cmd.servo_id)
            if joint_name is None:
                continue
            t = threading.Thread(
                target=self._interpolate_joint,
                args=(joint_name, cmd.position, cmd.duration_ms),
                daemon=True,
            )
            threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def stream_commands(self, commands: list[ServoCommand]) -> None:
        """Glide joints to new targets without waiting -- for continuous
        streams (follow mode).

        send_commands blocks for the whole move and spawns a thread per
        servo, so follow mode got ~10-12 updates/s through and each 45 ms
        move was 2 coarse steps then standing still: jerky (2026-10-05). Here
        one background loop steps every joint every STREAM_TICK toward its
        newest target, starting from where it is now, and each move is
        stretched to outlast the gap to the next command, as on the real
        robot (hardware_controller STREAM_*).
        """
        now = time.monotonic()
        gap_ms = None if self._last_stream_at is None else (now - self._last_stream_at) * 1000
        self._last_stream_at = now
        with self._moves_lock:
            for cmd in commands:
                joint = JOINT_NAME_MAP.get(cmd.servo_id)
                if joint is None:
                    continue
                ms = cmd.duration_ms if gap_ms is None else max(cmd.duration_ms, gap_ms * STREAM_GAP_STRETCH)
                ms = min(STREAM_MAX_MS, max(STREAM_MIN_MS, ms))
                start = self._current(joint, now)
                self._moves[joint] = (start, servo_units_to_rad(cmd.position), now, ms / 1000)
            if self._streamer is None:
                self._streamer = threading.Thread(target=self._stream_loop, name="sim-stream", daemon=True)
                self._streamer.start()

    def _current(self, joint: str, now: float) -> float:
        """Where a joint is in its streamed move right now (caller holds the lock)."""
        move = self._moves.get(joint)
        if move is None:
            return self._sim.get_joint_position(joint)
        start, target, t0, dur = move
        a = min(1.0, (now - t0) / dur) if dur > 0 else 1.0
        return start + (target - start) * a

    def _stream_loop(self) -> None:
        while True:
            now = time.monotonic()
            with self._moves_lock:
                for joint in list(self._moves):
                    _, target, t0, dur = self._moves[joint]
                    self._sim.set_joint_position(joint, self._current(joint, now))
                    if now - t0 >= dur:
                        del self._moves[joint]
            time.sleep(self.STREAM_TICK)

    def _interpolate_joint(self, joint_name: str, target_units: int, duration_ms: int) -> None:
        target_rad = servo_units_to_rad(target_units)
        start_rad = self._sim.get_joint_position(joint_name)
        steps = max(1, duration_ms // 20)  # ~20ms per step
        for i in range(1, steps + 1):
            t = i / steps
            interpolated = start_rad + t * (target_rad - start_rad)
            self._sim.set_joint_position(joint_name, interpolated)
            time.sleep(0.02)

    def read_feedback(self, servo_ids: list[int]) -> list[ServoFeedback]:
        feedback = []
        for servo_id in servo_ids:
            joint_name = JOINT_NAME_MAP.get(servo_id)
            if joint_name is None:
                continue
            rad = self._sim.get_joint_position(joint_name)
            feedback.append(ServoFeedback(
                servo_id=servo_id,
                position=rad_to_servo_units(rad),
                temperature=35,    # nominal safe temperature
                voltage=11100,     # nominal full battery (11.1V in mV)
            ))
        return feedback

    def reset_to_stand(self) -> None:
        self._sim.reset_pose()

    def get_joint_positions(self) -> dict[str, int]:
        return {
            joint: rad_to_servo_units(rad)
            for joint, rad in self._sim.get_all_joint_states().items()
        }
