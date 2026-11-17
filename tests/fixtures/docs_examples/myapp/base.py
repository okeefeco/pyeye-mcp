"""Shared base classes."""


class ConfigBase:
    """Settings loaded from somewhere."""

    source = "defaults"

    def load(self) -> dict:
        """Return the raw settings."""
        return {}
