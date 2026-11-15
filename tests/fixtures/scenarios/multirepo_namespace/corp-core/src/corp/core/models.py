"""Core models shared across the ``corp`` namespace."""

import logging

LOG = logging.getLogger(__name__)


class Base:
    """Root of the cross-repo hierarchy."""

    def __init__(self, name: str) -> None:
        self.name = name

    def describe(self) -> str:
        """Describe this object."""
        return f"{type(self).__name__}({self.name})"


class Shared:
    """Defined here AND in corp.tools.widgets: a cross-repo name collision."""


def make(name: str) -> Base:
    """Build a Base."""
    LOG.debug("make %s", name)
    return Base(name)
