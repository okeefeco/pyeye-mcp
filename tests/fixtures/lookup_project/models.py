"""Models for the lookup project fixture."""

from __future__ import annotations

from .enums import Status


class ServiceConfig:
    """Configuration for a service."""

    host: str = "localhost"
    port: int = 8080
    debug: bool = False
    tags: list[str] = []

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8080,
        debug: bool = False,
        tags: list[str] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.debug = debug
        self.tags = tags if tags is not None else []


class ServiceManager:
    """Manages a service lifecycle."""

    def __init__(self, config: ServiceConfig, name: str = "default") -> None:
        self.config = config
        self.name = name

    def start(self, port: int = 8080) -> bool:
        """Start the service on the given port."""
        self._port = port  # noqa: SLF001
        return True

    def stop(self) -> None:
        """Stop the service."""
        pass

    def get_config(self) -> ServiceConfig:
        """Return the current service configuration."""
        return self.config


class ExtendedManager(ServiceManager):
    """Extended manager with additional capabilities."""

    def start(self, port: int = 8080) -> bool:
        """Start with extended behaviour."""
        return super().start(port)


class StatusTracker:
    """Tracks service status — uses Status enum from enums module.

    This tests contextual type resolution: the type annotation 'Status'
    should resolve to enums.Status (the enum), not ambiguous.Status
    (the rendering class), because this file imports from enums.
    """

    current: Status = Status.PENDING

    def update(self, new_status: Status) -> None:
        """Update the current status."""
        self.current = new_status
