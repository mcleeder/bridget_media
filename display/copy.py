"""User-facing strings for every screen.

Centralised so the voice stays consistent and so wording changes never mean
hunting through render methods. Constants only — no logic, no state.

Two registers, on purpose:

* **Navigation** — headers and row labels — stays plain. These are read at a
  glance, often mid-tap, and flavour text on a 35px row costs more than it
  gives.
* **Status, empty and error messages** — the full-body notices — carry the
  voice. They are the moments the device has nothing to show anyway.

Status copy is drawn by `list_layout.draw_status_message`, which wraps to at
most 3 lines of roughly 45 characters — about 135 characters total. Anything
longer is silently ellipsised, so keep new copy inside that budget.
"""

from __future__ import annotations

from typing import Final

# --- Headers ------------------------------------------------------------

HEADER_HOME: Final[str] = "Bridget Media"
HEADER_PODCASTS: Final[str] = "Podcasts"
HEADER_QUEUE: Final[str] = "Next"
HEADER_BLUETOOTH: Final[str] = "Bluetooth"
HEADER_ADD_DEVICE: Final[str] = "Add device"
HEADER_RADIO: Final[str] = "Radio"
HEADER_WIFI: Final[str] = "Wi-Fi"
HEADER_WIFI_SETUP: Final[str] = "Setup mode"
HEADER_SLEEP_TIMER: Final[str] = "Sleep timer"

# --- Row labels ---------------------------------------------------------

HOME_ITEM_BLUETOOTH: Final[str] = "Bluetooth"
HOME_ITEM_PODCASTS: Final[str] = "Podcasts"
HOME_ITEM_QUEUE: Final[str] = "Next"
HOME_ITEM_RADIO: Final[str] = "Radio"
HOME_ITEM_WIFI: Final[str] = "Wi-Fi"

# Shown under the station name on the radio player. These streams carry no
# track metadata, so "live" is genuinely all the device knows.
# The radio player speaks French: the station is French, the panel has the
# glyphs, and "En direct" is what a French broadcaster actually says.
RADIO_LIVE: Final[str] = "En direct"
# French guillemets around the track title, spaced the French way.
QUOTE_OPEN: Final[str] = "«"
QUOTE_CLOSE: Final[str] = "»"
RADIO_ALBUM_SEPARATOR: Final[str] = " · "

# Suffix for a minutes value, on the duration grid and the player badge.
SLEEP_MINUTES_SUFFIX: Final[str] = "m"

DEVICE_CONNECTED: Final[str] = "Connected"
DEVICE_TAP_TO_CONNECT: Final[str] = "Tap to connect"
DEVICE_TAP_TO_PAIR: Final[str] = "Tap to pair"

# --- Status / empty / error messages ------------------------------------

BLUETOOTH_UNREACHABLE: Final[str] = "Spotted: a Pi with no Bluetooth to speak of. Tragic."
BLUETOOTH_NO_PAIRED: Final[str] = (
    "Your little black book is empty. Tap the search icon and go find someone."
)
BLUETOOTH_SCANNING: Final[str] = "Combing the room for new talent…"
BLUETOOTH_NOBODY_FOUND: Final[str] = (
    "Nobody worth knowing turned up. Put yours in pairing mode and try again."
)

# Formatted with the device name by ScreenManager.
BLUETOOTH_PAIRING: Final[str] = "Making introductions with {name}…"
BLUETOOTH_CONNECTING: Final[str] = "Getting cozy with {name}…"
BLUETOOTH_PAIRING_FAILED: Final[str] = "{name} left you on read. Try deploy/pair_speaker.sh."

# Wi-Fi status line labels sit on a 35px row under the network name, so they
# stay as plain and short as the Bluetooth ones.
WIFI_CONNECTED: Final[str] = "Connected"
WIFI_NO_INTERNET: Final[str] = "No internet"
WIFI_HOTSPOT_ACTIVE: Final[str] = "Setup hotspot"
WIFI_NO_ADDRESS: Final[str] = "No address yet"

# Labels on the setup-hotspot screen. Plain, not voicey: someone is copying
# these onto a phone, possibly a friend who has never seen the device before.
WIFI_SETUP_JOIN_LABEL: Final[str] = "Join this Wi-Fi"
WIFI_SETUP_PASSWORD_LABEL: Final[str] = "Password"
WIFI_SETUP_OPEN_LABEL: Final[str] = "Then open"

WIFI_CHECKING: Final[str] = "Asking around about the network…"
WIFI_UNREACHABLE: Final[str] = (
    "This box has no idea what a network is. Nothing to report."
)
WIFI_OFFLINE: Final[str] = (
    "Off the grid entirely. No Wi-Fi, no gossip, no downloads."
)

WIFI_HOTSPOT_STARTING: Final[str] = "Throwing my own network. Give me a moment…"
WIFI_HOTSPOT_FAILED: Final[str] = (
    "Could not get a hotspot up. Plug in a screen and a keyboard, darling."
)
WIFI_NO_CREDENTIALS: Final[str] = (
    "No hotspot credentials on this box. Re-run deploy/setup_pi.sh."
)

QUEUE_EMPTY: Final[str] = "Your evening is wide open."
NO_STATIONS: Final[str] = "The airwaves are empty. Someone cut the STATIONS list."
NO_PODCASTS: Final[str] = (
    "Not one subscription to your name. Add a few from the feed manager."
)

# Drawn inline between the title and the controls on Now Playing — one short
# line only, unlike the full-body notices above.
PLAYER_UNREACHABLE: Final[str] = "The DJ has gone missing."
