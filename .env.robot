# Robot hardware mode configuration
# Copy values from .env and add/override the robot-specific ones below.
# Usage:
#   cp .env.robot .env.robot.local      # make a local copy
#   edit .env.robot.local               # fill in your values
#   set -a && source .env.robot.local   # load into shell
#   uv run robot                        # start server in robot mode

# ── Robot network ────────────────────────────────────────────────────────────
# IP address of the physical AiNex robot on your network.
ROBOT_IP=

# HTTP port the robot_agent.py server listens on.
ROBOT_AGENT_PORT=9000

# ── API keys (copy from .env) ─────────────────────────────────────────────────
OPENAI_API_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com

# ── Robot mode flag (set automatically by `uv run robot`) ─────────────────────
# You can also set this manually to switch modes without changing scripts:
#   ROBOT_MODE=sim    → MuJoCo simulation (default for `uv run server`)
#   ROBOT_MODE=robot  → physical robot (default for `uv run robot`)
ROBOT_MODE=robot
