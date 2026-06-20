"""Shared conformance vector for relative-import resolution (#426).

Two resolvers historically derived "resolve a relative import to absolute":

1. ``import_analyzer.resolve_relative_import`` — the module-level seam (#421),
   used by the import dependency graph and the #405 ``find_subclasses`` AST
   resolution tables.
2. ``JediAnalyzer._resolve_relative_import`` — a separate (deprecated) static
   method feeding ``imported_by`` (#343) and ``analyze_dependencies``.

They had **different signatures and different package-detection strategies**
(an explicit ``is_package`` flag vs the seam's ``level == len(parts)``
heuristic) and so silently diverged on nested-package ``__init__`` imports —
the seam was wrong there. #426 consolidates them onto one correct
implementation that carries an explicit package bit.

This module is the single source of truth for the expected behaviour. Each
vector is asserted against **both** entry points, so the two can never drift
again. The expected values are the Python-correct resolutions.
"""

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.import_analyzer import resolve_relative_import

# (current_module, imported_module, level, is_package, expected)
#
# `current_module` is the importer's dotted name (for a package __init__ this
# is the package name itself). `is_package` is True iff the importer is a
# package __init__. These are the Python-correct absolute resolutions.
_VECTORS = [
    # --- regular modules: the package is the parent of the module name ---
    ("pkg.sub.mod", None, 1, False, "pkg.sub"),  # from . import X
    ("pkg.sub.mod", "other", 1, False, "pkg.sub.other"),  # from .other import X
    ("pkg.sub.mod", "other", 2, False, "pkg.other"),  # from ..other import X
    ("pkg.mod", None, 2, False, None),  # from .. import X — beyond top-level pkg → None
    ("pkg.mod", None, 3, False, None),  # walks above the root → None
    # --- nested package __init__: the package IS its own anchor (#426 bug) ---
    ("pkg.sub", None, 1, True, "pkg.sub"),  # from . import X  (was wrongly "pkg")
    ("pkg.sub", "mod", 1, True, "pkg.sub.mod"),  # from .mod import X (was "pkg.mod")
    ("pkg.sub", "other", 2, True, "pkg.other"),  # from ..other (was "pkg.sub.other")
    ("pkg.sub", None, 2, True, "pkg"),  # from .. import X
    ("pkg.sub", None, 3, True, None),  # above root → None
    # --- top-level package __init__: heuristic and explicit flag agreed here ---
    ("pkg", None, 1, True, "pkg"),  # from . import X
    ("pkg", "impl", 1, True, "pkg.impl"),  # from .impl import X
    # --- absolute from-import (level 0) is returned unchanged ---
    ("pkg.sub.mod", "abs.target", 0, False, "abs.target"),
    ("pkg.sub.mod", "abs.target", 0, True, "abs.target"),
]


@pytest.mark.parametrize("current,imported,level,is_pkg,expected", _VECTORS)
def test_seam_resolves_correctly(current, imported, level, is_pkg, expected):
    """The module-level seam returns the Python-correct absolute path."""
    assert resolve_relative_import(current, imported, level, is_pkg) == expected


@pytest.mark.parametrize("current,imported,level,is_pkg,expected", _VECTORS)
def test_jedi_resolver_agrees_with_seam(current, imported, level, is_pkg, expected):
    """The (deprecated) JediAnalyzer resolver agrees with the seam on every vector.

    Note the different parameter order — ``(level, module, importer_module,
    importer_is_package)`` — which is precisely why the two were error-prone to
    keep in sync by hand.
    """
    assert JediAnalyzer._resolve_relative_import(level, imported, current, is_pkg) == expected
