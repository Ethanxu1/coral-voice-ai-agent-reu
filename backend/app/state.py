from dataclasses import dataclass

from app.robot.sim_controller import SimController
from app.robot.hardware_controller import AiNexHardwareController
from app.follow_controller import FollowController
from app.simulator import AiNexSimulator
from app.collision.collision_checker import CollisionChecker
from app.collision.stability_checker import StabilityChecker


@dataclass
class AppState:
    simulator: AiNexSimulator | None = None
    sim_dispatcher: SimController | None = None
    hardware_dispatcher: AiNexHardwareController | None = None
    robot_mode: str = "sim"
    follow_controller: FollowController | None = None
    collision_checker: CollisionChecker | None = None
    stability_checker: StabilityChecker | None = None
    hardware_in_sync: bool = False


state = AppState()
