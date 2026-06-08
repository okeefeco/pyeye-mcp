"""Fixture for project/external boundary conformance test (Phase 7.3).

Defines a project class extending an external (stdlib) class so the
conformance test can verify edge_counts.subclasses on the external handle
returns project-internal subclasses (this one) only.
"""

from pathlib import PurePath


class _ProjectPathExtension(PurePath):
    """A project-internal class extending stdlib PurePath."""

    def __new__(cls, *args: str) -> "_ProjectPathExtension":
        """Construct a PurePath instance (required for PurePath subclassing)."""
        return super().__new__(cls, *args)
