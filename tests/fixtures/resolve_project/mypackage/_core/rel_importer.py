"""Importer that reaches widgets via a relative ``from`` import.

Exercises the ``ast.ImportFrom`` + ``_resolve_relative_import`` path of
``find_importers``: ``from .widgets import make_widget`` is a level-1 relative
import that resolves to ``mypackage._core.widgets`` without ever spelling the
absolute path textually.
"""

from .widgets import make_widget

__all__ = ["build"]


def build() -> object:
    """Return a widget, referencing the relative import so it is used."""
    return make_widget("rel")
