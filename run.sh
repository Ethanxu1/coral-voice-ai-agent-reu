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
set -m  # enable job control so each background job gets its own process group

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

# Ports the stack needs. Fail fast if any are already bound so the user gets a
# clear error instead of three services silently competing.
REQUIRED_PORTS=(8000 8001 5002)
if command -v ss >/dev/null 2>&1; then
    PORT_CHECK_CMD="ss"
elif command -v netstat >/dev/null 2>&1; then
    PORT_CHECK_CMD="netstat"
else
    PORT_CHECK_CMD=""
fi

check_port() {
    local port="$1"
    if [[ "$PORT_CHECK_CMD" == "ss" ]]; then
        ss -H -tln "sport = :$port" 2>/dev/null | grep -q .
    elif [[ "$PORT_CHECK_CMD" == "netstat" ]]; then
        netstat -an 2>/dev/null | grep -E "^[[:space:]]*tcp[[:space:]]+.*[[:space:]]0\.0\.0\.0\.$port|127\.0\.0\.1\.$port[[:space:]]+.*LISTEN" >/dev/null
    else
        # Fallback: try to bind to the port briefly. Non-portable but better than nothing.
        (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null
    fi
}

check_required_ports() {
    local busy=()
    for port in "${REQUIRED_PORTS[@]}"; do
        if check_port "$port"; then
            busy+=("$port")
        fi
    done
    if [[ ${#busy[@]} -gt 0 ]]; then
        echo "Error: required port(s) already in use: ${busy[*]}" >&2
        echo "Stop the other process(es) first, or change the stack ports." >&2
        exit 1
    fi
}

check_required_ports

PIDS=()
CLEANING_UP=0

cleanup() {
    if [[ "$CLEANING_UP" -ne 0 ]]; then
        return
    fi
    CLEANING_UP=1
    echo "Stopping..."
    for pid in "${PIDS[@]}"; do
        # Kill the entire process group so uv/uvicorn/npm children go down too.
        kill -- -"$pid" >/dev/null 2>&1 || true
    done
    sleep 0.5
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" >/dev/null 2>&1; then
            kill -9 -- -"$pid" >/dev/null 2>&1 || true
        fi
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
