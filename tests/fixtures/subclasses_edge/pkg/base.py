"""Base class under test for the ``subclasses`` expand edge (issue #348).

Canonical handle: ``pkg.base.Animal``.

Topology exercised by the resolver tests:

- ``pkg.middle.Mammal``      — DIRECT subclass (importable package module)
- ``pkg.middle.Dog``         — INDIRECT (grandchild) via Mammal
- ``script_animal.Lizard``   — DIRECT subclass defined in a NON-importable,
                               script-style module at the project root

``Loner`` is a sibling base with NO subclasses (measured-empty case).
"""


class Animal:
    """Top of the inheritance chain under test."""

    legs: int = 4


class Loner:
    """A class nobody subclasses — measured-empty subclasses case."""

    pass
