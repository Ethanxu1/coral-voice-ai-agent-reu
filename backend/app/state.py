from dataclasses import dataclass

from app.collision.collision_checker import CollisionChecker
from app.collision.stability_checker import StabilityChecker
from app.follow_controller import FollowController
from app.robot.hardware_controller import AiNexHardwareController
from app.robot.sim_controller import SimController
from app.simulator import AiNexSimulator


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
