"""Fixture for the ``imports`` edge honesty floor (#494).

Mixes a resolvable import with statically-present imports that Jedi cannot
resolve (a non-existent module, and a non-existent name from a real module).
The ``imports`` edge must surface the unresolvable ones in
``unresolved_imports`` instead of silently dropping them.

Canonical handle: ``mypackage._core.unresolved_imports_fixture``
"""

from os import _made_up_attr_494  # noqa: F401  # unresolvable name in a real module

from _nonexistent_pkg_494 import missing_symbol  # noqa: F401  # unresolvable module

from .widgets import make_widget  # resolvable project import

_REF = make_widget
