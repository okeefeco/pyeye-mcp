"""Tests for PEP 420 namespace support in the ``submodules`` enumerator (#423, Task 4).

A namespace package (no ``__init__.py``) may be spread across several *portions*
living under different sys.path roots.  ``_package_dirs`` must return the
**union** of those portion directories, and ``_enumerate_submodule_paths`` must
dedupe children **by name across portions, first-portion-wins** — where
"first" is decided by the analyzer's ``roots`` order (sys.path precedence),
NOT by the child-name sort.  That determinism is the #419-class hazard the
collision tests below pin in both directions.

Fixtures (real on-disk dirs, NOT tmp symlinks — the macOS Jedi-symlink hazard):

- ``ns_a/company/`` — portion A: ``auth.py`` + ``shared.py`` (no ``__init__.py``)
- ``ns_b/company/`` — portion B: ``api.py``  + ``shared.py`` (no ``__init__.py``)

``shared`` collides deliberately; whichever portion sorts first in ``roots``
must win.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.edges import _enumerate_submodule_paths, _package_dirs

_CONTAINMENT = Path(__file__).parent / "fixtures" / "containment"
_NS_A = _CONTAINMENT / "ns_a"
_NS_B = _CONTAINMENT / "ns_b"


class _NameStub:
    """Minimal Jedi-``Name``-like stand-in for a namespace package handle.

    A PEP 420 namespace package has no single ``module_path`` (no
    ``__init__.py``), so Jedi may not surface ``company`` as a resolvable
    handle.  ``_package_dirs`` only reads ``full_name``/``module_path`` via
    ``getattr``, so this stub drives the namespace branch directly per the
    plan's Task 4 note.
    """

    def __init__(self, full_name: str, module_path: Path | None = None) -> None:
        self.full_name = full_name
        self.module_path = module_path


@pytest.fixture
def ns_analyzer() -> JediAnalyzer:
    """Analyzer whose roots put ``ns_a`` before ``ns_b`` (portion A wins)."""
    analyzer = JediAnalyzer(str(_CONTAINMENT))
    analyzer.source_roots = []
    analyzer.added_sys_path = [_NS_A, _NS_B]
    return analyzer


@pytest.fixture
def ns_analyzer_reversed() -> JediAnalyzer:
    """Same fixtures, roots reversed (``ns_b`` first → portion B wins)."""
    analyzer = JediAnalyzer(str(_CONTAINMENT))
    analyzer.source_roots = []
    analyzer.added_sys_path = [_NS_B, _NS_A]
    return analyzer


def _company() -> Any:
    return _NameStub("company", module_path=None)


class TestPackageDirsNamespace:
    """``_package_dirs`` unions the matching portion directories."""

    def test_unions_both_portions(self, ns_analyzer: JediAnalyzer) -> None:
        dirs = {d.as_posix() for d in _package_dirs(_company(), ns_analyzer)}
        assert dirs == {
            (_NS_A / "company").as_posix(),
            (_NS_B / "company").as_posix(),
        }

    def test_portions_have_no_init(self, ns_analyzer: JediAnalyzer) -> None:
        for d in _package_dirs(_company(), ns_analyzer):
            assert not (d / "__init__.py").exists()

    def test_portion_order_follows_roots(self, ns_analyzer: JediAnalyzer) -> None:
        # ns_a precedes ns_b in roots → portion A dir comes first.
        dirs = _package_dirs(_company(), ns_analyzer)
        assert dirs[0].as_posix() == (_NS_A / "company").as_posix()

    def test_regular_package_unaffected(self, ns_analyzer: JediAnalyzer) -> None:
        # A regular package handle (module_path → __init__.py) stays single-dir.
        regular = _NameStub("mypkg", module_path=_CONTAINMENT / "regular" / "mypkg" / "__init__.py")
        dirs = _package_dirs(regular, ns_analyzer)
        assert [d.as_posix() for d in dirs] == [(_CONTAINMENT / "regular" / "mypkg").as_posix()]

    def test_plain_module_stays_empty(self, ns_analyzer: JediAnalyzer) -> None:
        # module_path is a real .py file → not a package, even in namespace mode.
        plain = _NameStub("company.auth", module_path=_NS_A / "company" / "auth.py")
        assert _package_dirs(plain, ns_analyzer) == []


class TestEnumerateNamespaceUnion:
    """Children are unioned + deduped across portions, first-portion-wins."""

    def test_child_handles_union_deduped(self, ns_analyzer: JediAnalyzer) -> None:
        entries = _enumerate_submodule_paths(_company(), ns_analyzer)
        handles = {e.handle for e in entries}
        assert handles == {"company.auth", "company.api", "company.shared"}

    def test_collision_winner_is_portion_a(self, ns_analyzer: JediAnalyzer) -> None:
        # company.shared exists in BOTH portions; ns_a precedes ns_b in roots,
        # so the winning file MUST be the portion-A shared.py.  This pins the
        # determinism invariant (#419 class).
        entries = _enumerate_submodule_paths(_company(), ns_analyzer)
        shared = next(e for e in entries if e.handle == "company.shared")
        assert shared.file.as_posix() == (_NS_A / "company" / "shared.py").as_posix()

    def test_collision_winner_flips_with_roots_order(
        self, ns_analyzer_reversed: JediAnalyzer
    ) -> None:
        # Reversing roots flips the winner to portion B — proving the winner
        # rides on roots order, not the name-sort.
        entries = _enumerate_submodule_paths(_company(), ns_analyzer_reversed)
        shared = next(e for e in entries if e.handle == "company.shared")
        assert shared.file.as_posix() == (_NS_B / "company" / "shared.py").as_posix()

    def test_still_sorted_by_child_name(self, ns_analyzer: JediAnalyzer) -> None:
        entries = _enumerate_submodule_paths(_company(), ns_analyzer)
        assert [e.handle for e in entries] == [
            "company.api",
            "company.auth",
            "company.shared",
        ]
