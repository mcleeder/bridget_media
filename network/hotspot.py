from __future__ import annotations

import json
import logging
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import config

logger = logging.getLogger(__name__)

# The password is read off a 296x128 e-ink panel and typed into a phone by
# someone who did not choose it. The QR code is the happy path, but the text
# underneath has to be usable when a camera refuses to focus — and a random
# character string is miserable to transcribe, because every character has to
# be read individually and there is no way to tell you have mistyped one.
#
# Words fix that: they are chunked, self-checking, and can be held in the head
# for the length of a glance away from the screen. The digits are the cheapest
# characters to add — a contiguous run on the numeric row — so they carry the
# tail of the entropy.
#
# Two words from a 1295-word list plus six digits is ~41 bits.
_PASSWORD_WORDS: Final[int] = 2
_PASSWORD_DIGITS: Final[int] = 6
_PASSWORD_SEPARATOR: Final[str] = "_"
_DIGIT_ALPHABET: Final[str] = "0123456789"
# A truncated or half-written word list must fail loudly rather than quietly
# generating a password out of whatever few words survived.
_MINIMUM_WORDS: Final[int] = 256

# Distinguishes two boxes sitting in the same room. Stable once generated.
_SUFFIX_ALPHABET: Final[str] = "abcdefghijkmnopqrstuvwxyz23456789"
_SUFFIX_LENGTH: Final[int] = 4

_SSID_PREFIX: Final[str] = "Bridge-Hotpot"

_OWNER_READ_WRITE: Final[int] = stat.S_IRUSR | stat.S_IWUSR


class HotspotCredentialsError(Exception):
    pass


@dataclass(frozen=True)
class HotspotCredentials:
    ssid: str
    password: str


def _load_words(path: str) -> list[str]:
    """Read the word list, rejecting anything that would weaken the password."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise HotspotCredentialsError(f"Could not read the word list at {path}") from exc

    words = [
        line.strip()
        for line in lines
        if line.strip() and not line.startswith("#")
    ]
    if any(not re.fullmatch(r"[a-z]+", word) for word in words):
        raise HotspotCredentialsError(f"Word list at {path} has non-lowercase entries")
    if len(set(words)) != len(words):
        raise HotspotCredentialsError(f"Word list at {path} has duplicates")
    if len(words) < _MINIMUM_WORDS:
        raise HotspotCredentialsError(
            f"Word list at {path} has only {len(words)} words, need {_MINIMUM_WORDS}"
        )
    return words


def _generate() -> HotspotCredentials:
    words = _load_words(config.HOTSPOT_WORDLIST_PATH)
    suffix = "".join(secrets.choice(_SUFFIX_ALPHABET) for _ in range(_SUFFIX_LENGTH))
    # sample() rather than repeated choice(): two identical words would read as
    # a bug to whoever has to type it. The entropy cost is under a thousandth
    # of a bit.
    chosen = secrets.SystemRandom().sample(words, _PASSWORD_WORDS)
    digits = "".join(secrets.choice(_DIGIT_ALPHABET) for _ in range(_PASSWORD_DIGITS))
    password = _PASSWORD_SEPARATOR.join([*chosen, digits])
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
