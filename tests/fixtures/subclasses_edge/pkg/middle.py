"""Direct and indirect subclasses of ``pkg.base.Animal`` (issue #348).

- ``Mammal`` is a DIRECT subclass of ``Animal``.
- ``Dog`` is an INDIRECT (grandchild) subclass of ``Animal`` via ``Mammal``.

Both live in this importable package module.
"""

from pkg.base import Animal


class Mammal(Animal):
    """Direct subclass of Animal."""

    warm_blooded: bool = True


class Dog(Mammal):
    """Indirect (grandchild) subclass of Animal via Mammal."""

    breed: str = "mutt"
