from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ServoCommand:
    servo_id: int
    position: int    # Hiwonder scale: 0–1000 (maps to 0–240°)
    duration_ms: int  # Movement time in milliseconds (0–30000)


@dataclass
class ServoFeedback:
    servo_id: int
    position: int    # 0–1000
    temperature: int  # Celsius (physical robot: warn >50°C)
    voltage: int     # millivolts (physical robot: warn <9000mV)


class RobotController(ABC):
    @abstractmethod
    def send_commands(self, commands: list[ServoCommand]) -> None: ...

    @abstractmethod
    def read_feedback(self, servo_ids: list[int]) -> list[ServoFeedback]: ...

    @abstractmethod
    def reset_to_stand(self) -> None: ...

    @abstractmethod
    def get_joint_positions(self) -> dict[str, int]: ...  # returns 0–1000 scale
