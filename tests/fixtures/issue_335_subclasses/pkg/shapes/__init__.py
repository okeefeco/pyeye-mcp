"""Public surface for the shapes subpackage — re-exports the Shape definition.

This is the re-export boundary that issue #335 Bug A is about:
``pkg.shapes.Shape`` and ``pkg.shapes._impl.Shape`` bind to the same object.
"""

from pkg.shapes._impl import Shape

__all__ = ["Shape"]
