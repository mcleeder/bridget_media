#!/usr/bin/env bash
# One-time: set up passwordless SSH to the Pi so deploy.sh doesn't prompt.
#
# Run from Windows in Git Bash:
#   bash deploy/setup_ssh_key.sh
#
# You'll be asked for the Pi password (it's PI_PASSWORD in .env) once or twice;
# after that, key auth takes over.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

env_get() {
    sed -n "s/^$1=//p" "$ROOT/.env" | tr -d '\r'
}

PI_USERNAME="$(env_get PI_USERNAME)"
PI_NETWORK_NAME="$(env_get PI_NETWORK_NAME)"
HOST="${PI_HOST:-${PI_NETWORK_NAME}.local}"
TARGET="${PI_USERNAME}@${HOST}"

KEY="$HOME/.ssh/id_ed25519"
if [[ ! -f "$KEY" ]]; then
    echo "No SSH key found — generating one..."
    ssh-keygen -t ed25519 -f "$KEY" -N "" -C "pi_media deploy"
fi

echo "Installing public key on ${TARGET} (enter the Pi password from .env when prompted)..."
if command -v ssh-copy-id >/dev/null 2>&1; then
    ssh-copy-id -i "${KEY}.pub" "$TARGET"
else
    ssh "$TARGET" 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys' < "${KEY}.pub"
fi

echo "Testing key auth..."
ssh -o PasswordAuthentication=no "$TARGET" 'echo "Key auth works: $(hostname)"'
