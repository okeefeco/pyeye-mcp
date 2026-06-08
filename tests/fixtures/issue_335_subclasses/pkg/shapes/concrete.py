"""Subclasses of Shape that inherit via the re-exported public path.

Both Circle and Square extend the *re-exported* ``pkg.shapes.Shape`` rather
than the definition-site ``pkg.shapes._impl.Shape``.  Issue #335 Bug A: when
the caller queries by one path and Jedi resolves the base to the other, exact
string equality drops these genuine subclasses.

- Circle inherits via ``from pkg.shapes import Shape`` (imported name).
- Square inherits via attribute access ``pkg.shapes.Shape`` (dotted base).
"""

import pkg.shapes
from pkg.shapes import Shape


class Circle(Shape):
    """Subclass via re-exported imported name."""

    sides = 0


class Square(pkg.shapes.Shape):
    """Subclass via re-exported dotted/attribute base."""

    sides = 4
