"""Client module that imports and uses symbols from models and utils."""

from __future__ import annotations

from .models import ServiceConfig, ServiceManager
from .utils import MAX_RETRIES, create_manager


def build_client(retries: int = MAX_RETRIES) -> ServiceManager:
    """Build a default client ServiceManager.

    Args:
        retries: Number of retries allowed. Defaults to MAX_RETRIES.

    Returns:
        A configured ServiceManager for use as a client.
    """
    config = ServiceConfig()
    manager = create_manager("client", config)
    manager._retries = retries  # noqa: SLF001
    return manager
