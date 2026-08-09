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

# --- Row labels ---------------------------------------------------------

HOME_ITEM_BLUETOOTH: Final[str] = "Bluetooth"
HOME_ITEM_PODCASTS: Final[str] = "Podcasts"
HOME_ITEM_QUEUE: Final[str] = "Next"

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

QUEUE_EMPTY: Final[str] = "Your evening is wide open."
NO_PODCASTS: Final[str] = (
    "Not one subscription to your name. Add a few from the feed manager."
)

# Drawn inline between the title and the controls on Now Playing — one short
# line only, unlike the full-body notices above.
PLAYER_UNREACHABLE: Final[str] = "The DJ has gone missing."
