"""Fixture module for NON-``if`` module-scope import guards (#360).

Companion to ``guarded_imports_fixture``: the guard forms here are a ``with``
block and a ``try``/``else`` block rather than an ``if``.  Both still bind at
MODULE scope, so the same rule applies — excluded from ``members``, included in
``imports``.

Canonical handle: ``mypackage._core.deep_guarded_imports_fixture``
"""

from contextlib import suppress

with suppress(ImportError):
    from .widgets import Widget

try:
    import os
except ImportError:  # pragma: no cover - stdlib is always importable
    os = None
else:
    from .widgets import Config

# Suppress F401 unused-import: reference the guarded imports.
_REF = (Widget, os, Config)
