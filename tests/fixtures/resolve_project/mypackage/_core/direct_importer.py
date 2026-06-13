"""Importer that reaches widgets via a direct ``import`` statement.

Exercises the ``ast.Import`` path of ``find_importers``:
``import mypackage._core.widgets`` matches ``alias.name == module_path``.
"""

import mypackage._core.widgets

__all__ = ["build"]


def build() -> object:
    """Return a widget, referencing the direct import so it is used."""
    return mypackage._core.widgets.make_widget("direct")
