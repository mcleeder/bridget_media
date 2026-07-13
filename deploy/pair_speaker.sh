#!/usr/bin/env bash
# Pair a Bluetooth speaker with the Pi over SSH.
#
# Run from Windows in Git Bash:
#   bash deploy/pair_speaker.sh --scan                  # list nearby MACs/names
#   bash deploy/pair_speaker.sh AA:BB:CC:DD:EE:FF        # pair + configure
#
# Reads PI_USERNAME / PI_NETWORK_NAME from .env in the repo root, same as
# deploy.sh / setup_ssh_key.sh. Assumes passwordless SSH key auth is already
# set up (bash deploy/setup_ssh_key.sh).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

env_get() {
    sed -n "s/^$1=//p" "$ROOT/.env" | tr -d '\r'
}

PI_USERNAME="$(env_get PI_USERNAME)"
PI_NETWORK_NAME="$(env_get PI_NETWORK_NAME)"
HOST="${PI_HOST:-${PI_NETWORK_NAME}.local}"
TARGET="${PI_USERNAME}@${HOST}"

if [[ -z "$PI_USERNAME" || -z "$PI_NETWORK_NAME" ]]; then
    echo "ERROR: PI_USERNAME / PI_NETWORK_NAME not found in $ROOT/.env" >&2
    exit 1
fi

if [[ $# -ne 1 ]]; then
    echo "Usage: bash deploy/pair_speaker.sh --scan | AA:BB:CC:DD:EE:FF" >&2
    exit 1
fi

if [[ "$1" == "--scan" ]]; then
    echo "Scanning for nearby Bluetooth devices on ${TARGET} (15s)..."
    ssh "$TARGET" '
        sudo rfkill unblock bluetooth
        bluetoothctl power on
        bluetoothctl --timeout 15 scan on
    '
    echo "Re-run with the MAC of your speaker: bash deploy/pair_speaker.sh AA:BB:CC:DD:EE:FF"
    exit 0
fi

MAC="$1"
if [[ ! "$MAC" =~ ^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$ ]]; then
    echo "ERROR: not a MAC address: $MAC" >&2
    echo "Usage: bash deploy/pair_speaker.sh --scan | AA:BB:CC:DD:EE:FF" >&2
    exit 1
fi

echo "Pairing ${MAC} on ${TARGET}..."
ssh "$TARGET" "
    sudo rfkill unblock bluetooth
    bluetoothctl power on
    # A scan sighting is required before pair will accept the MAC — an
    # hcitool scan sighting alone isn't enough.
    bluetoothctl --timeout 15 scan on
    bluetoothctl pair '${MAC}'
    bluetoothctl trust '${MAC}'
    bluetoothctl connect '${MAC}'
    configure-speaker '${MAC}'
"

echo "Done. ${MAC} is paired, trusted, and configured as the MPD output."
