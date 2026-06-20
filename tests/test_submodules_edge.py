"""Tests for the ``submodules`` containment edge primitives (#423).

This file is the home for the ``submodules`` edge tests landed across Tasks
2–10.  Task 2 covers :func:`edges._package_dirs` — the base case a later
enumerator builds on: resolving a *regular* package handle to its single
on-disk directory.

``_package_dirs`` makes the regular-vs-namespace decision ONCE by inspecting
the resolved handle's ``module_path``:

- ``module_path`` ends in ``__init__.py`` → **regular** package → return the
  single parent directory of that ``__init__.py``.
- otherwise (a plain ``X.py`` module, or a namespace portion with no
  ``__init__.py``) → the namespace branch, which Task 2 leaves as ``[]``.

The fixtures under ``tests/fixtures/containment/`` are REAL directories (NOT
tmp symlinks — Jedi misbehaves on macOS symlinked tmp dirs) and are reused by
Tasks 3–10:

- ``regular/mypkg/`` — a regular package (``__init__.py``) with ``alpha.py``,
  ``beta.py``, a ``sub/`` subpackage, plus junk (``__pycache__``, ``data/``)
  that later tasks assert are skipped.
- ``ns_a/company/`` and ``ns_b/company/`` — two PEP 420 namespace portions
  (NO ``__init__.py``) with a deliberate ``shared.py`` name collision.  Not
  exercised by Task 2 but created now because Task 4 depends on them.
"""

from pathlib import Path

import pytest

from pyeye._module_sentinel import ModuleSentinel
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.edges import _package_dirs
from pyeye.mcp.operations.inspect import _find_jedi_name_for_handle

_CONTAINMENT = Path(__file__).parent / "fixtures" / "containment"
_REGULAR = _CONTAINMENT / "regular"
_MYPKG = _REGULAR / "mypkg"

_A_HANDLE = "mypkg.alpha.A"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the regular-package fixture root."""
    return JediAnalyzer(str(_REGULAR))


# ---------------------------------------------------------------------------
# Task 2 — _package_dirs: regular package + empty-return cases
# ---------------------------------------------------------------------------


class TestPackageDirsRegular:
    """A regular package handle resolves to its single ``__init__.py`` parent dir."""

    def test_regular_package_returns_single_parent_dir(self, analyzer: JediAnalyzer) -> None:
        # A regular package: module_path ends in __init__.py → [<that dir>].
        sentinel = ModuleSentinel(_MYPKG / "__init__.py", "mypkg", analyzer)
        dirs = _package_dirs(sentinel, analyzer)
        assert [d.as_posix() for d in dirs] == [_MYPKG.as_posix()]

    def test_subpackage_returns_its_own_dir(self, analyzer: JediAnalyzer) -> None:
        # Subpackages are regular packages too (sub/__init__.py).
        sub = _MYPKG / "sub"
        sentinel = ModuleSentinel(sub / "__init__.py", "mypkg.sub", analyzer)
        dirs = _package_dirs(sentinel, analyzer)
        assert [d.as_posix() for d in dirs] == [sub.as_posix()]


class TestPackageDirsEmpty:
    """Non-package handles return ``[]`` (regular branch only in Task 2)."""

    def test_plain_module_returns_empty(self, analyzer: JediAnalyzer) -> None:
        # A non-package module: module_path is X.py (not __init__.py) → [].
        # (Task 2 leaves the namespace branch returning []; this exercises it.)
        sentinel = ModuleSentinel(_MYPKG / "alpha.py", "mypkg.alpha", analyzer)
        assert _package_dirs(sentinel, analyzer) == []

    def test_class_handle_returns_empty(self, analyzer: JediAnalyzer) -> None:
        # A class handle (resolved through the real analyzer/Jedi): not a
        # package — its module_path is alpha.py, so the regular branch is not
        # taken and Task 2's namespace branch returns [].
        jedi_name = _find_jedi_name_for_handle(_A_HANDLE, analyzer)
        assert jedi_name is not None, f"Could not resolve handle {_A_HANDLE!r}"
        assert _package_dirs(jedi_name, analyzer) == []

    def test_none_module_path_returns_empty(self, analyzer: JediAnalyzer) -> None:
        # A handle-like object whose module_path is None tolerates gracefully → [].
        sentinel = ModuleSentinel(_MYPKG / "__init__.py", "mypkg", analyzer)
        sentinel.module_path = None
        assert _package_dirs(sentinel, analyzer) == []
