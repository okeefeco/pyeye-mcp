"""Fixture exercising the ``from ... import *`` (wildcard) branch of imports.

``resolve_imports`` SKIPS wildcard targets — they are not statically
enumerable (mirrors ``_module_members``'s wildcard gap).  This module pairs a
wildcard import with one ordinary import so a test can prove BOTH halves:

- ``from .widgets import *``  → SKIPPED: none of ``Widget`` / ``make_widget`` /
  ``DEFAULT_NAME`` (the names ``*`` would bind) appear among the import handles.
- ``import os``              → KEPT: the ordinary import still resolves, proving
  the resolver ran PAST the wildcard rather than aborting on it.

Canonical handle: ``mypackage._core.wildcard_fixture``
"""

import os  # noqa: F401

from .widgets import *  # noqa: F401,F403

# Reference a wildcard-bound name + os so ruff sees the imports as used.
_REF = (os, make_widget)  # noqa: F405
