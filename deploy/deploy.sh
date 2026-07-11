#!/usr/bin/env bash
# Push the project to the Pi and restart the service.
#
# Run from Windows in Git Bash (or any POSIX shell):
#   bash deploy/deploy.sh
#
# Reads PI_USERNAME / PI_NETWORK_NAME from .env in the repo root.
# Override the target host with:  PI_HOST=192.168.1.50 bash deploy/deploy.sh
#
# Uses tar-over-ssh (rsync isn't available on stock Git Bash). Note: files
# deleted locally are NOT removed on the Pi; wipe ~/pi_media there if layout
# changes drastically.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

env_get() {
    # tr strips CR in case .env was saved with Windows line endings
    sed -n "s/^$1=//p" "$ROOT/.env" | tr -d '\r'
}

PI_USERNAME="$(env_get PI_USERNAME)"
PI_NETWORK_NAME="$(env_get PI_NETWORK_NAME)"
HOST="${PI_HOST:-${PI_NETWORK_NAME}.local}"
TARGET="${PI_USERNAME}@${HOST}"
APP_DIR="pi_media"

if [[ -z "$PI_USERNAME" || -z "$PI_NETWORK_NAME" ]]; then
    echo "ERROR: PI_USERNAME / PI_NETWORK_NAME not found in $ROOT/.env" >&2
    exit 1
fi

echo "Deploying to ${TARGET}:~/${APP_DIR} ..."

tar -C "$ROOT" -czf - \
    --exclude='.git' \
    --exclude='.env' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.mypy_cache' \
    --exclude='.ruff_cache' \
    --exclude='.claude' \
    --exclude='pi_media.db' \
    . | ssh "$TARGET" "mkdir -p ~/${APP_DIR} && tar -xzf - -C ~/${APP_DIR}"

echo "Code synced."

# Restart the app only if the service has been installed (first deploy happens
# before setup_pi.sh has run, so the service may not exist yet).
ssh "$TARGET" '
    if systemctl list-unit-files pi-media.service --no-legend 2>/dev/null | grep -q pi-media; then
        sudo systemctl restart pi-media
        echo "pi-media service restarted."
    else
        echo "pi-media service not installed yet — run: bash ~/pi_media/deploy/setup_pi.sh"
    fi
'

echo "Done."
