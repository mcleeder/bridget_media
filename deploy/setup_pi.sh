#!/usr/bin/env bash
# One-shot provisioning for a freshly flashed Pi (Pi OS Bookworm).
#
# Run ON THE PI, after the first deploy.sh has pushed the code:
#   bash ~/pi_media/deploy/setup_pi.sh
#
# Idempotent — safe to re-run after a partial failure.
#
# What it does:
#   1. apt packages: MPD + bluez-alsa for Bluetooth audio, Python GPIO/SPI/I2C libs
#   2. Enables SPI (e-ink) and I2C (touch) interfaces
#   3. Installs Python runtime deps (system Python, per project convention —
#      hence --break-system-packages on Bookworm)
#   4. Installs the Waveshare Touch e-Paper library (TP_lib) plus a
#      waveshare_epd shim package matching our imports
#   5. Installs /etc/mpd.conf (Bluetooth + aux outputs; speaker MAC filled in later)
#   6. Sets the mDNS hostname so the box answers to <MDNS_HOSTNAME>.local
#   7. Installs the passwordless-sudo allowlist the app needs
#   8. Installs + enables the pi-media systemd service
#   9. Installs + enables the pi-media-feeds (web feed manager) systemd service
#  10. Generates the per-device setup-hotspot credentials, installs the
#      captive-portal DNS drop-in and the network watchdog timer
#
# Manual step remaining afterwards: pair the Bluetooth speaker (instructions
# printed at the end).

set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="$(whoami)"

echo "=== [1/10] apt packages ==="
sudo apt-get update
sudo apt-get install -y \
    git \
    mpd mpc \
    bluez bluez-alsa-utils \
    avahi-daemon \
    network-manager \
    python3-pip \
    python3-pil \
    python3-spidev \
    python3-rpi.gpio \
    python3-smbus \
    python3-gpiozero \
    python3-lgpio

echo "=== [2/10] enable SPI + I2C ==="
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_i2c 0
# Hardware access for the app user. bluetooth is needed because
# BluetoothController's `bluetoothctl connect` runs as this user, not root
# (unlike configure-speaker, which runs via passwordless sudo).
sudo usermod -aG spi,i2c,gpio,bluetooth "$RUN_USER"

echo "=== [3/10] Python runtime deps ==="
# Pillow comes from apt (python3-pil) — building it with pip on a Zero W takes
# forever. The rest are pure Python and quick. requirements.txt stays the
# source of truth for local dev; keep this list in sync with its runtime section.
sudo pip3 install --break-system-packages \
    "feedparser>=6.0" \
    "python-mpd2>=3.0" \
    "APScheduler>=3.10,<4.0" \
    "Flask>=3.0" \
    "waitress>=3.0" \
    "requests>=2.31" \
    "segno>=1.6"

echo "=== [4/10] Waveshare Touch e-Paper library ==="
WAVESHARE_DIR="/opt/Touch_e-Paper_HAT"
if [[ ! -d "$WAVESHARE_DIR" ]]; then
    sudo git clone --depth 1 https://github.com/waveshareteam/Touch_e-Paper_HAT "$WAVESHARE_DIR"
fi
# The repo ships its Python modules (epd2in9_V2, icnt86, epdconfig) in a
# package named TP_lib; display/drivers/waveshare.py imports TP_lib directly.
TP_LIB_DIR="$(find "$WAVESHARE_DIR" -type d -name TP_lib | head -n 1)"
if [[ -z "$TP_LIB_DIR" ]]; then
    echo "ERROR: TP_lib not found in $WAVESHARE_DIR — repo layout changed?" >&2
    exit 1
fi
SITE_PACKAGES="$(python3 -c 'import site; print(site.getsitepackages()[0])')"
sudo cp -r "$TP_LIB_DIR" "$SITE_PACKAGES/"
# Clean up the waveshare_epd shim an earlier setup_pi.sh version installed
sudo rm -rf "$SITE_PACKAGES/waveshare_epd"
python3 -c "from TP_lib import epd2in9_V2, icnt86; epd2in9_V2.EPD_2IN9_V2; icnt86.INCT86" \
    && echo "TP_lib import OK" \
    || echo "WARNING: TP_lib import failed — check module names in $SITE_PACKAGES/TP_lib"

echo "=== [5/10] MPD config ==="
if [[ -f /etc/mpd.conf && ! -f /etc/mpd.conf.orig ]]; then
    sudo cp /etc/mpd.conf /etc/mpd.conf.orig
fi
# Don't clobber a config that already has a real speaker MAC in it
if ! sudo grep -q "bluealsa:DEV=..:" /etc/mpd.conf 2>/dev/null; then
    sudo cp "$APP_DIR/deploy/mpd.conf" /etc/mpd.conf
fi
# The guard above permanently blocks the full-file copy once a speaker MAC is
# configured, so the aux output needs its own independent append to reach an
# already-provisioned Pi.
if ! sudo grep -q 'name        "Aux output"' /etc/mpd.conf; then
    sudo tee -a /etc/mpd.conf > /dev/null <<'EOF'

audio_output {
    type        "alsa"
    name        "Aux output"
    device      "plughw:CARD=Headphones"
    mixer_type  "software"
}
EOF
    sudo systemctl restart mpd
fi
# bluez-alsa access for the mpd daemon user
sudo usermod -aG bluetooth,audio mpd
sudo systemctl enable mpd

# Helper to wire in the speaker once it's paired
sudo tee /usr/local/bin/configure-speaker > /dev/null <<'EOF'
#!/usr/bin/env bash
# Usage: configure-speaker AA:BB:CC:DD:EE:FF
set -euo pipefail
if [[ ! "${1:-}" =~ ^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$ ]]; then
    echo "Usage: configure-speaker AA:BB:CC:DD:EE:FF" >&2
    exit 1
fi
sudo sed -i "s/@SPEAKER_MAC@/$1/; s/DEV=\([0-9A-Fa-f]\{2\}:\)\{5\}[0-9A-Fa-f]\{2\}/DEV=$1/" /etc/mpd.conf
sudo systemctl restart mpd
echo "MPD now outputs to $1. Test with:  mpc add <stream-url> && mpc play"
EOF
sudo chmod +x /usr/local/bin/configure-speaker

echo "=== [6/10] mDNS hostname ==="
# config.py is the single source of truth for the name, so the screen, the
# Host allowlist and avahi can never disagree about it.
HOSTNAME_TARGET="$(cd "$APP_DIR" && python3 -c 'import config; print(config.MDNS_HOSTNAME)')"
CURRENT_HOSTNAME="$(hostname)"
if [[ "$CURRENT_HOSTNAME" != "$HOSTNAME_TARGET" ]]; then
    sudo hostnamectl set-hostname "$HOSTNAME_TARGET"
    # /etc/hosts still maps the old name to 127.0.1.1; leaving it stale makes
    # sudo slow to resolve the host on every call.
    sudo sed -i "s/\b${CURRENT_HOSTNAME}\b/${HOSTNAME_TARGET}/g" /etc/hosts
    HOSTNAME_CHANGED="yes"
else
    HOSTNAME_CHANGED=""
fi
sudo systemctl enable --now avahi-daemon

echo "=== [7/10] passwordless sudo allowlist ==="
# The deploy tooling used to require NOPASSWD: ALL, which makes compromising
# the app user the same as being root — and Phase 9 hands that user nmcli.
# These are everything the app and deploy.sh actually need root for; each is
# matched with its arguments, so `nmcli` is the only open-ended entry.
SUDOERS_TMP="$(mktemp)"
cat > "$SUDOERS_TMP" <<EOF
# Installed by deploy/setup_pi.sh — do not edit by hand.
${RUN_USER} ALL=(ALL) NOPASSWD: /usr/sbin/rfkill unblock bluetooth
${RUN_USER} ALL=(ALL) NOPASSWD: /usr/local/bin/configure-speaker
${RUN_USER} ALL=(ALL) NOPASSWD: /usr/bin/nmcli
${RUN_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart mpd
${RUN_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart pi-media
${RUN_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart pi-media-feeds
${RUN_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl reset-failed pi-media
${RUN_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl reset-failed pi-media-feeds
EOF
# A malformed sudoers file can lock the user out of sudo entirely, so it is
# never installed without visudo agreeing it parses.
if sudo visudo -cf "$SUDOERS_TMP" > /dev/null; then
    sudo install -m 0440 -o root -g root "$SUDOERS_TMP" /etc/sudoers.d/020_pi-media
    echo "Installed /etc/sudoers.d/020_pi-media"
else
    echo "ERROR: generated sudoers file failed visudo -c; not installing" >&2
    rm -f "$SUDOERS_TMP"
    exit 1
fi
rm -f "$SUDOERS_TMP"

echo "=== [8/10] pi-media service ==="
sed "s|@USER@|$RUN_USER|; s|@APP_DIR@|$APP_DIR|" "$APP_DIR/deploy/pi-media.service" \
    | sudo tee /etc/systemd/system/pi-media.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable pi-media

echo "=== [9/10] pi-media-feeds (web feed manager) service ==="
sed "s|@USER@|$RUN_USER|; s|@APP_DIR@|$APP_DIR|" "$APP_DIR/deploy/pi-media-feeds.service" \
    | sudo tee /etc/systemd/system/pi-media-feeds.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable pi-media-feeds

echo "=== [10/10] setup hotspot + network watchdog ==="
# Generated as the app user, not root: the panel has to read this file to draw
# the join QR, and the watchdog runs as root so it can read it either way.
(cd "$APP_DIR" && python3 -c "
import config
from network.hotspot import ensure_credentials
credentials = ensure_credentials(config.HOTSPOT_CREDENTIALS_PATH)
print(f'Setup hotspot SSID: {credentials.ssid}')
")
# Wildcard DNS for the captive portal. NetworkManager applies this only to
# shared (hotspot) connections, never to normal client Wi-Fi.
sudo install -d -m 0755 /etc/NetworkManager/dnsmasq-shared.d
sudo install -m 0644 "$APP_DIR/deploy/dnsmasq-shared-portal.conf" \
    /etc/NetworkManager/dnsmasq-shared.d/bridget-portal.conf
for UNIT in bridget-netwatch.service bridget-netwatch.timer; do
    sed "s|@USER@|$RUN_USER|; s|@APP_DIR@|$APP_DIR|" "$APP_DIR/deploy/$UNIT" \
        | sudo tee "/etc/systemd/system/$UNIT" > /dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now bridget-netwatch.timer

cat <<EOF

============================================================
Provisioning done. Two manual steps remain:

1. Pair the Bluetooth speaker (put it in pairing mode first). From Windows:

     bash deploy/pair_speaker.sh --scan
     bash deploy/pair_speaker.sh AA:BB:CC:DD:EE:FF

   Or directly on the Pi:

     bluetoothctl
       scan on              # wait for the speaker's MAC to appear
       pair AA:BB:CC:DD:EE:FF
       trust AA:BB:CC:DD:EE:FF
       connect AA:BB:CC:DD:EE:FF
       exit

     configure-speaker AA:BB:CC:DD:EE:FF

2. Reboot so SPI/I2C and group changes take effect, which also
   starts the app:

     sudo reboot

After reboot:
  - hardware smoke test:   cd $APP_DIR && python3 test_display.py
  - app logs:              journalctl -u pi-media -f
  - feed manager:          http://${HOSTNAME_TARGET}.local
  - feed manager logs:     journalctl -u pi-media-feeds -f

Now that the sudo allowlist is in place, the blanket grant can go:

     sudo rm -f /etc/sudoers.d/010_${RUN_USER}-nopasswd

  (Re-running this script afterwards will ask for a password — it is the
   only thing here that still needs broad sudo.)
============================================================
EOF

if [[ -n "$HOSTNAME_CHANGED" ]]; then
cat <<EOF
!!! HOSTNAME CHANGED: ${CURRENT_HOSTNAME} -> ${HOSTNAME_TARGET}

    The deploy tooling still points at the old name. On your workstation:
      - set PI_NETWORK_NAME=${HOSTNAME_TARGET} in .env
      - clear the stale host key:  ssh-keygen -R ${CURRENT_HOSTNAME}.local

    Until then, deploy with:  PI_HOST=${CURRENT_HOSTNAME}.local bash deploy/deploy.sh
============================================================
EOF
fi
