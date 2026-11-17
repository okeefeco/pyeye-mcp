"""Command-line entry point."""

from .cache import Cache


class Settings:
    """Command-line settings (a second Settings, on purpose)."""

    verbose = False


def main() -> None:
    """Run the CLI."""
    cache = Cache()
    cache.evict("all")
