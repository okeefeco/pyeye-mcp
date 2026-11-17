"""A small cache."""

from .config import Settings


class DependencyTracker:
    """Tracks which keys depend on which."""

    def dependents(self, key: str) -> list[str]:
        """Keys that depend on *key*."""
        return [k for k in () if k != key]

    def forget(self, key: str) -> None:
        """Stop tracking *key*."""


class Cache:
    """An in-memory cache."""

    def __init__(self) -> None:
        """Create an empty cache."""
        self.tracker = DependencyTracker()
        self.settings = Settings()

    def evict(self, key: str) -> None:
        """Drop *key* and everything that depends on it."""
        for dependent in self.tracker.dependents(key):
            self.evict(dependent)
        self.tracker.forget(key)
