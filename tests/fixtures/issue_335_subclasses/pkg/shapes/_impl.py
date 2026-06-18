"""Definition site for Shape (issue #335 Bug A — re-export boundary).

Canonical handle: pkg.shapes._impl.Shape
Re-exported as pkg.shapes.Shape via shapes/__init__.py.
"""


class Shape:
    """Base shape, defined here and re-exported from the package surface."""

    sides: int = 0
