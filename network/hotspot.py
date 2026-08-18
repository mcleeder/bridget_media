from __future__ import annotations

import json
import logging
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

# Ambiguous characters are left out: this password is read off a 296x128 e-ink
# panel and typed into a phone by someone who did not choose it. The QR code
# is the happy path, but the text underneath has to be usable when a camera
# refuses to focus.
_PASSWORD_ALPHABET: Final[str] = "abcdefghijkmnopqrstuvwxyz23456789"
# WPA2 demands at least 8. Twelve keeps the QR payload short enough to stay a
# small symbol on the panel (see display/screens/wifi_setup.py) while leaving
# ~60 bits of entropy, which is far beyond what a 20-minute AP window needs.
_PASSWORD_LENGTH: Final[int] = 12

# Distinguishes two boxes sitting in the same room. Stable once generated.
_SUFFIX_ALPHABET: Final[str] = "abcdefghijkmnopqrstuvwxyz23456789"
_SUFFIX_LENGTH: Final[int] = 4

_SSID_PREFIX: Final[str] = "Bridget-Setup"

_OWNER_READ_WRITE: Final[int] = stat.S_IRUSR | stat.S_IWUSR


class HotspotCredentialsError(Exception):
    pass


@dataclass(frozen=True)
class HotspotCredentials:
    ssid: str
    password: str


def _generate() -> HotspotCredentials:
    suffix = "".join(secrets.choice(_SUFFIX_ALPHABET) for _ in range(_SUFFIX_LENGTH))
    password = "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(_PASSWORD_LENGTH))
    return HotspotCredentials(ssid=f"{_SSID_PREFIX}-{suffix}", password=password)


def _write(path: Path, credentials: HotspotCredentials) -> None:
    # Created 0600 from the start rather than chmod'ed afterwards, so the
    # password is never briefly world-readable on a shared filesystem.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _OWNER_READ_WRITE)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump({"ssid": credentials.ssid, "password": credentials.password}, handle)


def load_credentials(path: str) -> HotspotCredentials:
    """Read the hotspot credentials. Never generates them.

    The watchdog runs as root, so a file it created would be unreadable by the
    app user that has to render the QR — generating is therefore confined to
    ensure_credentials(), which provisioning and the web app call as that user.
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HotspotCredentialsError(
            f"No hotspot credentials at {path} — run deploy/setup_pi.sh"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise HotspotCredentialsError(f"Could not read hotspot credentials at {path}") from exc

    ssid = raw.get("ssid")
    password = raw.get("password")
    if not isinstance(ssid, str) or not isinstance(password, str) or not ssid or not password:
        raise HotspotCredentialsError(f"Hotspot credentials at {path} are malformed")
    return HotspotCredentials(ssid=ssid, password=password)


def ensure_credentials(path: str) -> HotspotCredentials:
    """Load the credentials, generating them once if they don't exist yet.

    Generated per device with `secrets`, never a constant: a password baked
    into the repo would be shared by every box handed to a friend, which is
    the textbook IoT failure.
    """
    target = Path(path)
    try:
        return load_credentials(path)
    except HotspotCredentialsError:
        if target.exists():
            raise

    credentials = _generate()
    try:
        _write(target, credentials)
    except FileExistsError:
        # Another process won the race; its file is as good as ours.
        return load_credentials(path)
    except OSError as exc:
        raise HotspotCredentialsError(f"Could not write hotspot credentials to {path}") from exc

    logger.info("Generated hotspot credentials for SSID %s", credentials.ssid)
    return credentials
