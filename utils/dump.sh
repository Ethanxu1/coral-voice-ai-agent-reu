#!/usr/bin/env zsh
# =============================================================================
# dump — copy a file from ainex_skeleton_following/ to the ainex Docker container
#
# Usage:
#   dump <file>
#   (then prompted) Write to: ros_ws/src/____
#
# One-time setup:
#   sudo mv dump.sh /usr/local/bin/dump && sudo chmod +x /usr/local/bin/dump
# =============================================================================

# ── CONFIG ────────────────────────────────────────────────────────────────────
REPO_ROOT="/Users/scottfukuda/ainex_skeleton_following"

PI_USER="pi"
PI_HOST="raspberrypi.local"
PI_PASSWORD="raspberrypi"

PI_SCP_BASE="/home/pi/scp"

CONTAINER_NAME="ainex"
CONTAINER_SRC_BASE="/home/ubuntu/ros_ws/src"
# ── END CONFIG ────────────────────────────────────────────────────────────────

BOLD='\033[1m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
DIM='\033[2m'
RESET='\033[0m'

# ── Usage guard ───────────────────────────────────────────────────────────────
if [[ $# -eq 0 ]]; then
  echo "${BOLD}Usage:${RESET} dump <file_or_dir>"
  echo "  Must be run from inside: ${DIM}${REPO_ROOT}${RESET}"
  exit 1
fi

INPUT_PATH="$1"

# ── Resolve absolute path ─────────────────────────────────────────────────────
if [[ "$INPUT_PATH" = /* ]]; then
  ABS_PATH="$INPUT_PATH"
else
  ABS_PATH="$(pwd)/${INPUT_PATH}"
fi
ABS_PATH="${ABS_PATH:A}"

# ── Verify file exists ────────────────────────────────────────────────────────
if [[ ! -e "$ABS_PATH" ]]; then
  echo "${RED}✗ Error:${RESET} '${INPUT_PATH}' does not exist."
  exit 1
fi

# ── Enforce repo root ─────────────────────────────────────────────────────────
if [[ "$ABS_PATH" != "${REPO_ROOT}"/* ]]; then
  echo "${RED}✗ Error:${RESET} File is not inside the project root."
  echo "  Expected: ${DIM}${REPO_ROOT}/${RESET}"
  echo "  Got:      ${DIM}${ABS_PATH}${RESET}"
  exit 1
fi

# ── Prompt for destination ────────────────────────────────────────────────────
FILENAME=$(basename "$ABS_PATH")
echo ""
printf "${BOLD}Write to:${RESET} ${DIM}/home/ubuntu/ros_ws/src/${RESET}"
read DEST_SUBDIR

# Strip any leading/trailing slashes
DEST_SUBDIR="${DEST_SUBDIR##/}"
DEST_SUBDIR="${DEST_SUBDIR%%/}"

if [[ -z "$DEST_SUBDIR" ]]; then
  echo "${RED}✗ Error:${RESET} Destination cannot be empty."
  exit 1
fi

# ── Compute all paths ─────────────────────────────────────────────────────────
REL_PATH="${ABS_PATH#${REPO_ROOT}/}"
REL_DIR="${REL_PATH%/*}"
[[ "$REL_DIR" == "$REL_PATH" ]] && REL_DIR=""

PI_DEST_DIR="${PI_SCP_BASE}/${REL_DIR}"
PI_DEST_FULL="${PI_SCP_BASE}/${REL_PATH}"
CONTAINER_DEST_FULL="${CONTAINER_SRC_BASE}/${DEST_SUBDIR}/${FILENAME}"

echo ""
echo "${BOLD}${CYAN}▶ dump${RESET}  ${BOLD}${FILENAME}${RESET}"
echo "  ${DIM}local${RESET}      ${ABS_PATH}"
echo "  ${CYAN}→${RESET} ${DIM}pi${RESET}        ${PI_USER}@${PI_HOST}:${PI_DEST_FULL}"
echo "  ${CYAN}→${RESET} ${DIM}container${RESET}  ${CONTAINER_NAME}:${CONTAINER_DEST_FULL}"
echo ""

# ── Check sshpass ─────────────────────────────────────────────────────────────
if ! command -v sshpass &>/dev/null; then
  echo "${RED}✗ sshpass not found.${RESET} Install with:  brew install sshpass"
  exit 1
fi

SSH=(sshpass -p "${PI_PASSWORD}" ssh -o StrictHostKeyChecking=no)
SCP=(sshpass -p "${PI_PASSWORD}" scp -o StrictHostKeyChecking=no)

# ── Step 1: SCP to Pi ─────────────────────────────────────────────────────────
echo "${YELLOW}[1/2]${RESET} SCP to Pi..."

"${SSH[@]}" "${PI_USER}@${PI_HOST}" "mkdir -p '${PI_DEST_DIR}'"
if [[ $? -ne 0 ]]; then
  echo "${RED}✗ SSH connection failed.${RESET} Check PI_HOST, PI_USER, and PI_PASSWORD."
  exit 1
fi

if [[ -d "$ABS_PATH" ]]; then
  "${SCP[@]}" -r "$ABS_PATH" "${PI_USER}@${PI_HOST}:${PI_DEST_DIR}/"
else
  "${SCP[@]}" "$ABS_PATH" "${PI_USER}@${PI_HOST}:${PI_DEST_FULL}"
fi

if [[ $? -ne 0 ]]; then
  echo "${RED}✗ SCP failed.${RESET}"
  exit 1
fi

# ── Step 2: docker cp into container ─────────────────────────────────────────
echo "${YELLOW}[2/2]${RESET} docker cp into '${CONTAINER_NAME}'..."

"${SSH[@]}" "${PI_USER}@${PI_HOST}" \
  "docker cp '${PI_DEST_FULL}' '${CONTAINER_NAME}:${CONTAINER_DEST_FULL}'"

if [[ $? -ne 0 ]]; then
  echo "${RED}✗ docker cp failed.${RESET}"
  echo "  Is '${CONTAINER_NAME}' running? Does '${CONTAINER_SRC_BASE}/${DEST_SUBDIR}/' exist inside it?"
  exit 1
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "${GREEN}${BOLD}✓ Done!${RESET}  ${CONTAINER_NAME}:${CONTAINER_DEST_FULL}"
echo ""
