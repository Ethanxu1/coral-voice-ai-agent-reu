#!/usr/bin/env bash
# Start the CORAL stack: main server (sim or hardware), vision server,
# optionally speaker, and the frontend dev server. Each process's output is
# piped into its own file under logs/.
#
# Usage:
#   ./run.sh                          # sim mode: uv run server
#   ./run.sh -live                    # hardware mode: uv run robot
#   ./run.sh -live -ip 192.168.8.219  # hardware mode, explicit robot IP
#   ./run.sh -speaker                 # also start uv run speaker
#   ./run.sh -live -ip 192.168.8.219 -speaker
set -euo pipefail

LIVE=false
ROBOT_IP=""
WITH_SPEAKER=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        -live)
            LIVE=true
            shift
            ;;
        -ip)
            if [[ $# -lt 2 ]]; then
                echo "Error: -ip requires a value" >&2
                exit 1
            fi
            ROBOT_IP="$2"
            shift 2
            ;;
        -speaker)
            WITH_SPEAKER=true
            shift
            ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "Usage: $0 [-live [-ip <robot_ip>]] [-speaker]" >&2
            exit 1
            ;;
    esac
done

if [[ -n "$ROBOT_IP" && "$LIVE" != true ]]; then
    echo "Error: -ip is only valid together with -live" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

PIDS=()

cleanup() {
    echo "Stopping..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" >/dev/null 2>&1 || true
    done
    wait >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

if [[ "$LIVE" == true ]]; then
    if [[ -n "$ROBOT_IP" ]]; then
        export ROBOT_IP
        echo "Starting robot server (hardware mode, ROBOT_IP=$ROBOT_IP) -> $LOG_DIR/server.log"
    else
        echo "Starting robot server (hardware mode, default ROBOT_IP) -> $LOG_DIR/server.log"
    fi
    uv run robot > "$LOG_DIR/server.log" 2>&1 &
else
    echo "Starting server (sim mode) -> $LOG_DIR/server.log"
    uv run server > "$LOG_DIR/server.log" 2>&1 &
fi
PIDS+=("$!")

echo "Starting vision server -> $LOG_DIR/vision.log"
uv run vision > "$LOG_DIR/vision.log" 2>&1 &
PIDS+=("$!")

if [[ "$WITH_SPEAKER" == true ]]; then
    echo "Starting speaker server -> $LOG_DIR/speaker.log"
    uv run speaker > "$LOG_DIR/speaker.log" 2>&1 &
    PIDS+=("$!")
fi

echo "Starting frontend dev server -> $LOG_DIR/frontend.log"
(cd "$SCRIPT_DIR/frontend" && npm run dev) > "$LOG_DIR/frontend.log" 2>&1 &
PIDS+=("$!")

echo "All processes started (pids: ${PIDS[*]}). Tail logs in $LOG_DIR/. Press Ctrl+C to stop."
wait
