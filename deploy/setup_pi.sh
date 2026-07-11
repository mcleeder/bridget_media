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
#   5. Installs /etc/mpd.conf (Bluetooth output, speaker MAC filled in later)
#   6. Installs + enables the pi-media systemd service
#
# Manual step remaining afterwards: pair the Bluetooth speaker (instructions
# printed at the end).

set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="$(whoami)"

echo "=== [1/6] apt packages ==="
sudo apt-get update
sudo apt-get install -y \
    git \
    mpd mpc \
    bluez bluez-alsa-utils \
    python3-pip \
    python3-pil \
    python3-spidev \
    python3-rpi.gpio \
    python3-smbus \
    python3-gpiozero \
    python3-lgpio

echo "=== [2/6] enable SPI + I2C ==="
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_i2c 0
# Hardware access for the app user
sudo usermod -aG spi,i2c,gpio "$RUN_USER"

echo "=== [3/6] Python runtime deps ==="
# Pillow comes from apt (python3-pil) — building it with pip on a Zero W takes
# forever. The rest are pure Python and quick. requirements.txt stays the
# source of truth for local dev; keep this list in sync with its runtime section.
sudo pip3 install --break-system-packages \
    "feedparser>=6.0" \
    "python-mpd2>=3.0" \
    "APScheduler>=3.10,<4.0"

echo "=== [4/6] Waveshare Touch e-Paper library ==="
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

echo "=== [5/6] MPD config ==="
if [[ -f /etc/mpd.conf && ! -f /etc/mpd.conf.orig ]]; then
    sudo cp /etc/mpd.conf /etc/mpd.conf.orig
fi
# Don't clobber a config that already has a real speaker MAC in it
if ! sudo grep -q "bluealsa:DEV=..:" /etc/mpd.conf 2>/dev/null; then
    sudo cp "$APP_DIR/deploy/mpd.conf" /etc/mpd.conf
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

echo "=== [6/6] pi-media service ==="
sed "s|@USER@|$RUN_USER|; s|@APP_DIR@|$APP_DIR|" "$APP_DIR/deploy/pi-media.service" \
    | sudo tee /etc/systemd/system/pi-media.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable pi-media

cat <<EOF

============================================================
Provisioning done. Two manual steps remain:

1. Pair the Bluetooth speaker (put it in pairing mode first):

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
============================================================
EOF
