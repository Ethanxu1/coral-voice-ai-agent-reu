"""FastAPI app factory, lifespan, and console entry points for Coral."""

from __future__ import annotations

import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from langfuse import Langfuse
from loguru import logger

from app import resource_path
from app.api.router import router as api_router
from app.collision.collision_checker import CollisionChecker
from app.collision.stability_checker import StabilityChecker
from app.config import (
    CORAL_HOST,
    CORAL_MUJOCO_WINDOW,
    CORAL_NO_VIEWER,
    ENABLE_COLLISION_CHECK,
    ENABLE_FALL_CHECK,
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
    ROBOT_IP,
    ROBOT_MODE,
)
from app.data.pose_db import clear_all_poses
from app.follow_controller import FollowController
from app.robot.hardware_controller import AiNexHardwareController
from app.robot.sim_controller import SimController
from app.services.motion import _sync_sim_to_hardware, dispatch_servo_commands
from app.services.transcription import _get_whisper_model
from app.simulator import AiNexSimulator
from app.state import state


# ---------------------------------------------------------------------------
# MuJoCo native viewer launch preference
# ---------------------------------------------------------------------------
def _viewer_opens_on_launch() -> bool:
    """Read the 'open the MuJoCo window at startup' preference.

    Off by default: most runs drive the browser viewer (/ws/sim), where the
    native window adds nothing and steals focus on every start.
    """
    return CORAL_MUJOCO_WINDOW


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------
def _run_startup_validation() -> None:
    """Log clear warnings for common deployment misconfigurations.

    These checks are non-fatal: the server stays up so a developer can inspect
    logs, but each warning is designed to be the first thing staff see when a
    school deployment is misconfigured.
    """
    from app.config import OPENAI_API_KEY, TTS_IS_ENABLED

    assets_dir = resource_path.repo_root() / "assets" / "ainex"
    if not assets_dir.is_dir() or not any(assets_dir.rglob("*.xml")):
        logger.warning(
            "MuJoCo AiNex assets not found under assets/ainex. "
            "The simulator and browser viewer will not work."
        )

    if TTS_IS_ENABLED and not OPENAI_API_KEY:
        logger.warning(
            "TTS is enabled (TTS_ENABLED=auto and no explicit disable), "
            "but OPENAI_API_KEY is not set. The robot will not speak."
        )
    elif TTS_IS_ENABLED:
        logger.info("TTS enabled with OpenAI API key present.")
    else:
        logger.info("TTS disabled.")

    db_parent = Path(resource_path.user_data_dir())
    try:
        db_parent.mkdir(parents=True, exist_ok=True)
        if not os.access(db_parent, os.W_OK):
            logger.warning(
                f"Pose DB directory is not writable: {db_parent}. "
                "Saved poses will not persist across sessions."
            )
    except Exception as exc:
        logger.warning(f"Could not verify pose DB directory: {exc}")


# ---------------------------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - start/stop simulator and Langfuse."""

    state.robot_mode = os.environ.get("ROBOT_MODE", ROBOT_MODE)

    clear_all_poses()
    logger.info("Pose database cleared for new session.")

    # Startup sanity checks — log clearly so deployment issues are obvious.
    _run_startup_validation()


    # Always start the MuJoCo simulator — in robot mode it provides a visualization
    # of what the code wants the robot to do, so we can compare to the physical motion.
    logger.info("Starting AiNex MuJoCo simulator...")
    state.simulator = AiNexSimulator()
    # Physics always runs; the native window is opt-in via CORAL_MUJOCO_WINDOW.
    state.simulator.start_viewer(open_window=_viewer_opens_on_launch())
    state.sim_dispatcher = SimController(state.simulator)

    if state.robot_mode in ("robot", "hardware"):
        logger.info(f"ROBOT MODE — targeting physical robot at {ROBOT_IP}")
        state.hardware_dispatcher = AiNexHardwareController()
        # Mirror physical pose into sim so the viewer starts where the robot actually is.
        _sync_sim_to_hardware()

    logger.info(f"Robot dispatchers initialized (mode={state.robot_mode})")

    if ENABLE_COLLISION_CHECK:
        state.collision_checker = CollisionChecker()
        logger.info("Collision checker enabled — waypoints will be shadow-rolled before dispatch")
    else:
        state.collision_checker = None
        logger.info("Collision checker disabled via ENABLE_COLLISION_CHECK=false")

    if ENABLE_FALL_CHECK:
        state.stability_checker = StabilityChecker()
        logger.info("Fall check enabled — moves that topple the robot will be blocked entirely")
    else:
        state.stability_checker = None
        logger.info("Fall check disabled via ENABLE_FALL_CHECK=false")

    state.follow_controller = FollowController(dispatch_servo_commands)

    langfuse_keys_present = bool(LANGFUSE_PUBLIC_KEY) and bool(LANGFUSE_SECRET_KEY)
    langfuse_client = Langfuse(tracing_enabled=langfuse_keys_present)
    if langfuse_keys_present:
        logger.info("Langfuse tracing initialized")
    else:
        logger.info(
            "LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY not set — Langfuse tracing disabled"
        )

    logger.info("Pre-loading Whisper STT model...")
    _get_whisper_model()
    logger.info("Whisper model ready.")

    yield

    if state.simulator is not None:
        logger.info("Stopping AiNex simulator...")
        state.simulator.stop_viewer()

    logger.info("Flushing Langfuse traces...")
    langfuse_client.flush()


# ---------------------------------------------------------------------------
# FastAPI app factory
# ---------------------------------------------------------------------------
def create_app() -> FastAPI:
    app = FastAPI(title="Coral AI Agent", lifespan=lifespan)

    # CORS middleware for frontend. Match any localhost/127.0.0.1 port via regex so a
    # Vite dev-server port bump never breaks cross-origin fetches.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Serve robot mesh assets (STL) so the browser viewer can load geometry.
    ASSETS_DIR = resource_path.repo_root() / "assets"
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

    app.include_router(api_router)
    return app


app = create_app()


# ---------------------------------------------------------------------------
# macOS mjpython re-exec
# ---------------------------------------------------------------------------
def _reexec_under_mjpython_if_needed(want_window: bool = True) -> None:
    """Re-exec under `mjpython` on macOS so the MuJoCo viewer window can open.

    MuJoCo's interactive viewer (`launch_passive`) raises on macOS unless the
    process is launched via `mjpython`, which keeps the Cocoa UI loop on the real
    main thread while running Python on a worker thread. Under plain `python` /
    `uv run` the viewer thread dies with:
        RuntimeError: `launch_passive` requires ... `mjpython` on macOS
    and no window appears (the server itself keeps running). Re-exec the current
    entry point under mjpython so `uv run server` / `uv run robot` show the robot.

    No-op off macOS, once already re-exec'd, when CORAL_NO_VIEWER=1, or when the
    caller says no window is wanted.
    """
    if not want_window:
        logger.info("MuJoCo window off for this launch — staying on plain python")
        return
    if sys.platform != "darwin":
        return
    if os.environ.get("CORAL_MJPYTHON") == "1" or CORAL_NO_VIEWER:
        return
    mjpython = Path(sys.executable).with_name("mjpython")
    if not mjpython.exists():
        logger.warning(
            "mjpython not found next to the interpreter; the MuJoCo viewer window "
            "won't open on macOS. Set CORAL_NO_VIEWER=1 to silence this."
        )
        return
    argv = sys.argv if sys.argv and Path(sys.argv[0]).exists() else ["-m", "app.main"]
    os.environ["CORAL_MJPYTHON"] = "1"
    logger.info("macOS: re-launching under mjpython so the MuJoCo viewer window opens...")
    os.execv(str(mjpython), [str(mjpython), *argv])


# ---------------------------------------------------------------------------
# Console entry points
# ---------------------------------------------------------------------------
def main():
    """Entry point for simulation mode (default — starts MuJoCo)."""
    _reexec_under_mjpython_if_needed(want_window=_viewer_opens_on_launch())
    logger.info("Starting Coral AI Agent server (sim mode)...")
    uvicorn.run(
        "app.main:app",
        host=CORAL_HOST,
        port=8000,
        reload=False,
        log_level="info",
    )


def main_robot():
    """Entry point for hardware robot mode."""
    # Set this before any imports or re-exec so the new process reads ROBOT_MODE=robot.
    os.environ["ROBOT_MODE"] = "robot"
    _reexec_under_mjpython_if_needed(want_window=_viewer_opens_on_launch())
    logger.info(f"Starting Coral AI Agent server in ROBOT mode (target: {ROBOT_IP})")
    logger.info("Frontend: run 'npm run dev' in the frontend/ directory")
    logger.info(f"Make sure robot_server.py is running on the robot at {ROBOT_IP}:9000")
    uvicorn.run(
        "app.main:app",
        host=CORAL_HOST,
        port=8000,
        reload=False,
        log_level="info",
    )


def main_sim_test():
    """Entry point for sim test mode — cycle the sim robot through every pose in motions.py."""
    from app.robot.hardware_angle_utils import hardware_units_to_rad
    from app.robot.motions import MOTIONS

    _reexec_under_mjpython_if_needed()

    hold_seconds = float(os.getenv("SIM_TEST_HOLD_SECONDS", "2.0"))

    requested = [a for a in sys.argv[1:] if not a.startswith("-")]
    names = requested or list(MOTIONS.keys())
    unknown = [n for n in names if n not in MOTIONS]
    if unknown:
        logger.error(f"Unknown motion(s): {unknown}. Available: {list(MOTIONS.keys())}")
        return

    logger.info("Starting AiNex MuJoCo simulator (sim test mode)...")
    sim = AiNexSimulator()
    sim.start_viewer()
    time.sleep(1.0)  # let the viewer window come up

    logger.info(f"Cycling through {len(names)} motion(s): {names}")
    try:
        while sim.is_running():
            for name in names:
                if not sim.is_running():
                    break
                motion = MOTIONS[name]
                logger.info(f"=== Motion: {name} ({len(motion)} frame(s)) ===")
                for pulse, duration_ms in motion:
                    ramps = []
                    for joint, units in pulse.items():
                        try:
                            start = sim.get_joint_position(joint)
                            target = hardware_units_to_rad(int(units), joint)
                        except Exception as e:  # unknown joint — skip, keep going
                            logger.debug(f"sim-test: skip joint {joint}: {e}")
                            continue
                        ramps.append((joint, start, target))
                    steps = max(1, int(duration_ms) // 20)
                    for i in range(1, steps + 1):
                        frac = i / steps
                        for joint, start, target in ramps:
                            sim.set_joint_position(joint, start + frac * (target - start))
                        time.sleep(0.02)
                time.sleep(hold_seconds)
                logger.info("  resetting to stand")
                sim.reset_pose()
                time.sleep(hold_seconds)
    except KeyboardInterrupt:
        logger.info("Interrupted — stopping sim test.")
    finally:
        sim.stop_viewer()


if __name__ == "__main__":
    main()
