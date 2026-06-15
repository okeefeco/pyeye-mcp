"""Fixture module for testing the ``imports`` edge resolver.

Top-level imports (the ONLY things this module imports, intentionally small):
- ``import os``                          → module ``os`` (stdlib, ast.Import form)
- ``from .widgets import make_widget``   → function ``mypackage._core.widgets.make_widget``
                                           (project symbol, ast.ImportFrom form)

This module deliberately has NO top-level function/class definitions so its
``members`` edge returns an empty list, keeping ``members`` ∩ ``imports`` = ∅
trivially for this fixture.

Canonical handle: ``mypackage._core.imports_fixture``
"""

import os

from .widgets import make_widget

# Suppress F401 unused-import: reference both imports so ruff is satisfied.
_REF = (os, make_widget)
