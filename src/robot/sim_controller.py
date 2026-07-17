import threading
import time

from robot.angle_utils import rad_to_servo_units, servo_units_to_rad
from robot.interface import RobotController, ServoCommand, ServoFeedback
from robot.servo_config import JOINT_NAME_MAP, SERVO_ID_MAP


class SimController(RobotController):
    """RobotController backend that drives the MuJoCo simulator instead of hardware.

    Each servo command is executed in its own thread to simulate the parallel
    motion the physical bus achieves when moving multiple servos simultaneously.
    """

    def __init__(self, simulator):
        self._sim = simulator

    def send_commands(self, commands: list[ServoCommand]) -> None:
        """Dispatch servo commands to the MuJoCo simulator.

        Spawns one thread per command to simulate concurrent timed motion,
        mirroring how the physical bus processes multi-servo move commands.
        """
        threads = []
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
