"""The sleep timer itself: a deadline and three pure functions over it.

No side effects and no clock reading — every function takes `now`, which is
what makes the whole thing testable without waiting out a real timer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# Offered on the duration screen. Exactly four: the screen is a 2x2 grid, and
# a fifth choice would cost the one-tap reachability that is the point of it.
DURATION_CHOICES: Final[tuple[int, ...]] = (15, 30, 45, 60)

_SECONDS_PER_MINUTE: Final[int] = 60


@dataclass(frozen=True)
class SleepTimer:
    """An armed sleep timer, held as an absolute monotonic deadline.

    Monotonic, never wall clock. The Pi 3B+ has no RTC, so after an offline
    boot the clock restores a stale value and then jumps forward when NTP
    lands; a wall-clock deadline would fire hours early or never at all, and
    both failures happen while the owner is asleep and cannot see them. The
    Phase 10 watchdog *had* to use wall clock because it exits between
    invocations — this lives inside one long-running process, so it doesn't.

    An absolute deadline, not "N minutes of playback": pausing does not pause
    the timer, because the user is falling asleep against wall time.
    """

    deadline: float


def start(minutes: int, now: float) -> SleepTimer:
    return SleepTimer(deadline=now + minutes * _SECONDS_PER_MINUTE)


def remaining_seconds(timer: SleepTimer, now: float) -> float:
    return max(0.0, timer.deadline - now)


def is_expired(timer: SleepTimer, now: float) -> bool:
    return now >= timer.deadline


def remaining_minutes(timer: SleepTimer, now: float) -> int:
    """Whole minutes left, rounded up — the number the badge shows.

    Rounded up so a timer set to 30 reads "30m" straight away rather than
    "29m", and so the final partial minute reads "1m" rather than "0m".
    """
    return -int(-remaining_seconds(timer, now) // _SECONDS_PER_MINUTE)
