"""Application configuration."""

from .base import ConfigBase


class Settings(ConfigBase):
    """The application's settings."""

    debug = False
    cache_size = 128

    def reload(self) -> None:
        """Re-read the settings."""
        self.load()


class DevSettings(Settings):
    """Settings for local development."""

    debug = True
