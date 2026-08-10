from __future__ import annotations


class DisplayError(Exception):
    """Any failure in the display layer — driver bring-up or rendering.

    Lives here rather than in manager.py so display/drivers/ can raise it
    without importing the manager (a driver has no business knowing about
    ScreenManager).
    """
