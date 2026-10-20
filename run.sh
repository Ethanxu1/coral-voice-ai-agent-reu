#!/usr/bin/env bash
# Start the CORAL stack:
#   - Postgres, the backend (:8000) and the frontend (:5173) in Docker
#     (docker compose), and
#   - the vision server (:8001) on the host, because it needs the webcam and
#     Docker on macOS cannot reach one.
# Output goes to logs/stack.log (containers) and logs/vision.log.
#
# Usage:
#   ./run.sh                          # simulation mode
#   ./run.sh -live                    # also drive the physical robot (ROBOT_IP from .env)
#   ./run.sh -live -ip 192.168.8.219  # physical robot at an explicit IP
set -euo pipefail
set -m  # job control: the vision server gets its own process group

LIVE=false
ROBOT_IP_ARG=""

usage() {
    echo "Usage: $0 [-live [-ip <robot_ip>]]" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -live) LIVE=true; shift ;;
        -ip)
            [[ $# -ge 2 ]] || { echo "Error: -ip requires a value" >&2; exit 1; }
            ROBOT_IP_ARG="$2"
            shift 2
            ;;
        *) echo "Unknown argument: $1" >&2; usage ;;
    esac
done

if [[ -n "$ROBOT_IP_ARG" && "$LIVE" != true ]]; then
    echo "Error: -ip is only valid together with -live" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR" "$SCRIPT_DIR/recordings"

for cmd in docker uv; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "Error: '$cmd' is required but not installed (see README.md)." >&2
        exit 1
    fi
done
if [[ ! -f .env ]]; then
    echo "Warning: no .env file; copy .env.example to .env and set OPENAI_API_KEY." >&2
fi

# Fail fast if a port the stack needs is taken, instead of a half-started stack.
REQUIRED_PORTS=(8000 8001 5173 "${POSTGRES_PORT:-5432}")
port_in_use() {
    if command -v ss >/dev/null 2>&1; then
        ss -H -tln "sport = :$1" 2>/dev/null | grep -q .
    elif command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
    else
        (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
    fi
}
busy=()
for port in "${REQUIRED_PORTS[@]}"; do
    if port_in_use "$port"; then busy+=("$port"); fi
done
if [[ ${#busy[@]} -gt 0 ]]; then
    echo "Error: required port(s) already in use: ${busy[*]}" >&2
    echo "Stop the other process(es) first (an old stack: docker compose down)." >&2
    exit 1
fi

if [[ "$LIVE" == true ]]; then
    export ROBOT_MODE=robot
    if [[ -n "$ROBOT_IP_ARG" ]]; then export ROBOT_IP="$ROBOT_IP_ARG"; fi
    echo "Hardware mode (ROBOT_IP=${ROBOT_IP:-from .env})"
else
    export ROBOT_MODE=sim
    echo "Simulation mode"
fi

# The backend container must reach the vision server on the host. Docker
# Desktop (macOS) forwards host.docker.internal to the host's loopback; on Linux
# the backend shares the host network instead (docker-compose.linux.yml).
if [[ "$(uname -s)" == "Linux" ]]; then
    export COMPOSE_FILE="docker-compose.yml:docker-compose.linux.yml"
fi

VISION_PID=""
LOGS_PID=""
CLEANING_UP=0
cleanup() {
    [[ "$CLEANING_UP" -ne 0 ]] && return
    CLEANING_UP=1
    echo "Stopping..."
    if [[ -n "$VISION_PID" ]]; then
        kill -- -"$VISION_PID" >/dev/null 2>&1 || true
    fi
    if [[ -n "$LOGS_PID" ]]; then
        kill "$LOGS_PID" >/dev/null 2>&1 || true
    fi
    docker compose down >/dev/null 2>&1 || true
    wait >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "Starting vision server on the host -> $LOG_DIR/vision.log"
uv run vision > "$LOG_DIR/vision.log" 2>&1 &
VISION_PID=$!

echo "Building and starting containers (first run downloads images and models)..."
docker compose up --build --detach --wait --wait-timeout 900
docker compose logs --follow --no-color > "$LOG_DIR/stack.log" 2>&1 &
LOGS_PID=$!

echo
echo "CORAL is running: http://localhost:5173"
echo "Logs: $LOG_DIR/stack.log, $LOG_DIR/vision.log. Press Ctrl+C to stop."
wait "$VISION_PID"
