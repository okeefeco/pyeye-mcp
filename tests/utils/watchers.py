"""Helpers for checking that tests leave no real file watchers running (#807)."""

from __future__ import annotations

import threading

from watchdog.observers.api import BaseObserver


def live_observers() -> list[threading.Thread]:
    """Every real watchdog observer thread still running in this process."""
    return [t for t in threading.enumerate() if isinstance(t, BaseObserver) and t.is_alive()]
