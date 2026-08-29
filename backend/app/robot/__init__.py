from app.robot.interface import RobotController


def get_controller(mode: str = "sim", simulator=None, **kwargs) -> RobotController:
    """Instantiate a RobotController for the given backend mode.

    Args:
        mode: "sim" for MuJoCo simulator (default), "robot" for physical robot.
        simulator: Existing AiNexSimulator instance to wrap (sim mode only).
    """
    if mode == "sim":
        if simulator is None:
            from app.simulator.mujoco_sim import AiNexSimulator
            simulator = AiNexSimulator(**kwargs)
        from app.robot.sim_controller import SimController
        return SimController(simulator)
    elif mode in ("robot", "hardware"):
        from app.robot.hardware_controller import AiNexHardwareController
        return AiNexHardwareController(**kwargs)
    else:
        raise ValueError(f"Unknown controller mode: {mode!r}")
