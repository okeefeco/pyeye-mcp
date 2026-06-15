"""Utility functions and constants for the lookup project fixture."""

from __future__ import annotations

from .models import ServiceConfig, ServiceManager

MAX_RETRIES: int = 3
DEFAULT_TIMEOUT = 30
API_BASE: str | None = None
COMPLEX_DEFAULT = ServiceConfig(host="prod.example.com")


def create_manager(name: str, config: ServiceConfig | None = None) -> ServiceManager:
    """Create a ServiceManager with the given name and optional config.

    Args:
        name: The name of the manager.
        config: Optional service configuration. Uses default if not provided.

    Returns:
        A new ServiceManager instance.
    """
    if config is None:
        config = ServiceConfig()
    return ServiceManager(config, name)


def helper(x, y=10):
    """Simple helper with no annotations."""
    return x + y
