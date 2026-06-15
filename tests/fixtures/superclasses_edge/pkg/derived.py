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


class GrandChild(Child):
    """Has exactly one direct superclass: ``pkg.derived.Child``.

    Exercises the direct-bases-not-MRO contract: ``resolve_superclasses`` must
    return only ``Child`` (the immediate parent), NOT the transitive ancestor
    ``pkg.bases.Base``.  The chain is ``GrandChild -> Child -> Base``.
    """

    extra2: str = "grandchild"


class Weird(
    NotDefinedAnywhere  # noqa: F821 — intentionally undefined to test goto-failure drop path
):  # base intentionally undefined — exercises the drop-and-diverge path
    # This file is only statically analyzed, never executed, so an undefined
    # name in the class header is safe.  The class tests that `resolve_superclasses`
    # drops unresolvable bases (edge_counts.superclasses == 0) while
    # `_get_superclasses` still records them as ast.unparse fallback strings
    # (superclasses field contains "NotDefinedAnywhere").
    pass


def function_in_module() -> None:
    """A plain function — non-class, wrong-kind case for superclasses tests."""


VAR_IN_MODULE: int = 42
