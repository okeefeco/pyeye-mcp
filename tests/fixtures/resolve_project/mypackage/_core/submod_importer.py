"""Importer that reaches widgets via the ``from package import submodule`` idiom.

Exercises the previously-missed ``ast.ImportFrom`` path of ``find_importers``
(#436): ``from mypackage._core import widgets`` imports the *submodule*
``widgets``. The ``from`` clause resolves to the package
``mypackage._core``; the submodule handle is reconstructed by appending the
imported name, so the importer must be attributed to
``mypackage._core.widgets`` even though that dotted path is never spelled.

Same top-level package as the target, so the textual pre-filter admits it via
``shares_package``; this isolates the AST-matching half of the fix.
"""

from mypackage._core import widgets

__all__ = ["build"]


def build() -> object:
    """Return a widget, referencing the submodule import so it is used."""
    return widgets.make_widget("submod")
