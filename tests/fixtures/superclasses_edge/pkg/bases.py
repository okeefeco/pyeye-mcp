"""Base classes for the superclasses-edge fixture (issue #361).

Canonical handles:
- ``pkg.bases.Base``      — a project-defined base class (no own superclasses)
- ``pkg.bases.Mixin``     — a second project-defined base class (no own superclasses)
- ``pkg.bases.Loner``     — a class with NO superclasses (measured-empty case)

Topology exercised by the superclasses resolver tests:

- ``pkg.derived.Child``        → DIRECT superclass: ``pkg.bases.Base``
- ``pkg.derived.MultiChild``   → TWO direct superclasses: ``pkg.bases.Base``,
                                 ``pkg.bases.Mixin``
- ``pkg.derived.ExternalChild``→ DIRECT superclass: external (``pathlib.PurePosixPath``)
- ``pkg.bases.Base``           → no superclasses (measured-empty case for the base itself)
"""


class Base:
    """Top-level project base class with no superclasses."""

    name: str = "base"


class Mixin:
    """A second project-level base class used for multiple-inheritance tests."""

    value: int = 0
