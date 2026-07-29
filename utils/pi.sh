#!/usr/bin/env zsh
# =============================================================================
# pi — SSH into the Pi and drop straight into the ainex container as ubuntu
#
# Usage:
#   pi
#
# One-time setup:
#   sudo mv pi.sh /usr/local/bin/pi && sudo chmod +x /usr/local/bin/pi
# =============================================================================

PI_USER="pi"
PI_HOST="raspberrypi.local"
PI_PASSWORD="raspberrypi"
CONTAINER_NAME="ainex"

if ! command -v sshpass &>/dev/null; then
  echo "✗ sshpass not found. Install with:  brew install sshpass"
  exit 1
fi

echo "Connecting to ${PI_USER}@${PI_HOST} → ${CONTAINER_NAME}..."

sshpass -p "$PI_PASSWORD" ssh -o StrictHostKeyChecking=no -t \
  "${PI_USER}@${PI_HOST}" \
  "docker exec -it ${CONTAINER_NAME} bash -c 'su - ubuntu && cd /home/ubuntu && exec bash'"
