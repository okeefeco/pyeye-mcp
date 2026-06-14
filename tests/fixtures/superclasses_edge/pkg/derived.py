"""Derived classes for the superclasses-edge fixture (issue #361).

Exercises the topology the ``superclasses`` expand resolver must handle:

- ``Child``         — one project superclass (``pkg.bases.Base``)
- ``MultiChild``    — two project superclasses (``pkg.bases.Base``, ``pkg.bases.Mixin``)
- ``ExternalChild`` — one external (stdlib) superclass (``pathlib.PurePosixPath``)
- ``function_in_module`` — a plain function (non-class, wrong-kind case)
- ``VAR_IN_MODULE`` — a module-level variable (non-class, wrong-kind case)
"""

from pathlib import PurePosixPath

from pkg.bases import Base, Mixin


class Child(Base):
    """Has exactly one project-internal superclass: ``pkg.bases.Base``."""

    extra: str = "child"


class MultiChild(Base, Mixin):
    """Has two project-internal superclasses: ``pkg.bases.Base`` and ``pkg.bases.Mixin``."""

    combined: str = "multi"


class ExternalChild(PurePosixPath):
    """Has one external (stdlib) superclass: ``pathlib.PurePosixPath``.

    Tests that external bases are included in the ``superclasses`` edge result.
    """

    def __new__(cls, *args: str) -> "ExternalChild":
        """Required for PurePosixPath subclassing."""
        return super().__new__(cls, *args)


def function_in_module() -> None:
    """A plain function — non-class, wrong-kind case for superclasses tests."""


VAR_IN_MODULE: int = 42
