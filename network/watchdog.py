"""Decides when the setup hotspot goes up and when it comes down.

Run one-shot from a systemd timer (`python -m network.watchdog`), not from
main.py's poll loop: if this lived in the player app, a crashed player would
also mean no way to fix the Wi-Fi — the exact failure that strands someone
with the box on a shelf and no SSH.

State has to survive between invocations, so it lives in a small JSON file
rather than in memory.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import config
from network.controller import NetworkController, NetworkError
from network.hotspot import HotspotCredentialsError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WatchdogState:
    consecutive_failures: int = 0
    hotspot_started_at: float | None = None


def _load_state(path: str) -> WatchdogState:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return WatchdogState()
    except (OSError, json.JSONDecodeError):
        # A corrupt state file must not wedge the watchdog forever: starting
        # over costs at most one extra offline interval.
        logger.warning("Discarding unreadable watchdog state at %s", path, exc_info=True)
        return WatchdogState()

    started_at = raw.get("hotspot_started_at")
    return WatchdogState(
        consecutive_failures=int(raw.get("consecutive_failures", 0)),
        hotspot_started_at=float(started_at) if isinstance(started_at, int | float) else None,
    )


def _save_state(path: str, state: WatchdogState) -> None:
    try:
        Path(path).write_text(
            json.dumps(
                {
                    "consecutive_failures": state.consecutive_failures,
                    "hotspot_started_at": state.hotspot_started_at,
                }
            ),
            encoding="utf-8",
        )
    except OSError:
        # Losing state degrades to "count from zero again", which is far
        # better than the timer unit failing every minute.
        logger.warning("Could not save watchdog state to %s", path, exc_info=True)


def _elapsed_since(started_at: float, now: float) -> float:
    """Seconds since the hotspot went up.

    Wall clock, not monotonic, because this process exits between checks — and
    the Pi 3B+ has no RTC, so a clock that jumps when NTP finally lands can
    make this negative or enormous. Both are treated as "expired": dropping an
    AP early is recoverable from the panel, leaving one up forever is not.

    `now` is passed in rather than read here so the whole decision is a
    function of its arguments — reading the clock internally made the lifetime
    cap untestable and silently ignored the caller's clock.
    """
    elapsed = now - started_at
    if elapsed < 0 or elapsed > config.HOTSPOT_MAX_LIFETIME_SEC:
        return config.HOTSPOT_MAX_LIFETIME_SEC
    return elapsed


def _handle_hotspot_up(
    controller: NetworkController, state: WatchdogState, now: float
) -> WatchdogState:
    if state.hotspot_started_at is None:
        # Raised by hand from the panel. Adopt it so the lifetime cap applies
        # to a manual hotspot exactly as it does to an automatic one.
        logger.info("Adopting a hotspot this watchdog did not start")
        return WatchdogState(consecutive_failures=0, hotspot_started_at=now)

    elapsed = _elapsed_since(state.hotspot_started_at, now)
    if elapsed < config.HOTSPOT_MAX_LIFETIME_SEC:
        logger.info("Hotspot up for %.0fs of %ds", elapsed, config.HOTSPOT_MAX_LIFETIME_SEC)
        return state

    # The cap is a security control, not a nicety: an AP left broadcasting
    # accepts Wi-Fi passwords over plain HTTP in a house nobody is watching.
    logger.info("Hotspot lifetime reached — dropping it and rejoining")
    controller.stop_hotspot()
    controller.reconnect_saved_network()
    return WatchdogState()


def _handle_offline(
    controller: NetworkController, state: WatchdogState, now: float
) -> WatchdogState:
    failures = state.consecutive_failures + 1
    if failures < config.OFFLINE_CHECKS_BEFORE_HOTSPOT:
        logger.info(
            "Offline (%d/%d checks before raising the hotspot)",
            failures,
            config.OFFLINE_CHECKS_BEFORE_HOTSPOT,
        )
        return WatchdogState(consecutive_failures=failures)

    credentials = controller.start_saved_hotspot()
    logger.info(
        "Offline for %d consecutive checks — raised hotspot %s", failures, credentials.ssid
    )
    return WatchdogState(consecutive_failures=0, hotspot_started_at=now)


def run_once(controller: NetworkController, state: WatchdogState, now: float) -> WatchdogState:
    """One check. Pure enough to test: all the I/O is behind `controller`."""
    status = controller.get_status()

    if status.is_hotspot_active:
        return _handle_hotspot_up(controller, state, now)
    if status.is_online:
        if state.consecutive_failures:
            logger.info("Back online via %s", status.ssid)
        return WatchdogState()
    return _handle_offline(controller, state, now)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    state = _load_state(config.NETWORK_WATCHDOG_STATE_PATH)
    try:
        controller = NetworkController(
            config.HOTSPOT_CREDENTIALS_PATH, config.NETWORK_SCAN_CACHE_PATH
        )
        next_state = run_once(controller, state, time.time())
    except (NetworkError, HotspotCredentialsError):
        # Exiting non-zero every minute would fill the journal and mark the
        # unit failed; the next tick retries anyway.
        logger.exception("Network watchdog check failed")
        return
    if next_state != state:
        _save_state(config.NETWORK_WATCHDOG_STATE_PATH, next_state)


if __name__ == "__main__":
    main()
