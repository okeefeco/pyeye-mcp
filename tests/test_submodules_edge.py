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
from pyeye.mcp.operations.edges import (
    EDGE_RESOLVERS,
    _dir_shallow_qualifies,
    _enumerate_submodule_paths,
    _package_dirs,
    edge_status,
    resolve_submodules,
)
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import _find_jedi_name_for_handle
from pyeye.mcp.operations.trace import trace

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


# ---------------------------------------------------------------------------
# Task 3 — _enumerate_submodule_paths: pure directory scan of a regular package
# ---------------------------------------------------------------------------


def _mypkg_sentinel(analyzer: JediAnalyzer) -> ModuleSentinel:
    """A ``ModuleSentinel`` for the ``mypkg`` regular-package fixture."""
    return ModuleSentinel(_MYPKG / "__init__.py", "mypkg", analyzer)


class TestEnumerateSubmodulePathsRegular:
    """Enumerating a regular package's DIRECT children from a pure dir scan."""

    def test_children_handles_exact_set(self, analyzer: JediAnalyzer) -> None:
        # EXACTLY the three real children — no __init__, __pycache__, or data.
        entries = _enumerate_submodule_paths(_mypkg_sentinel(analyzer), analyzer)
        handles = {e.handle for e in entries}
        assert handles == {"mypkg.alpha", "mypkg.beta", "mypkg.sub"}

    def test_sorted_by_child_name(self, analyzer: JediAnalyzer) -> None:
        # Deterministic order: sorted by the last dotted component (child name).
        entries = _enumerate_submodule_paths(_mypkg_sentinel(analyzer), analyzer)
        assert [e.handle for e in entries] == ["mypkg.alpha", "mypkg.beta", "mypkg.sub"]

    def test_module_child_is_not_subpackage(self, analyzer: JediAnalyzer) -> None:
        entries = _enumerate_submodule_paths(_mypkg_sentinel(analyzer), analyzer)
        alpha = next(e for e in entries if e.handle == "mypkg.alpha")
        assert alpha.is_subpackage is False
        assert alpha.file.name == "alpha.py"

    def test_regular_subpackage_points_at_init(self, analyzer: JediAnalyzer) -> None:
        entries = _enumerate_submodule_paths(_mypkg_sentinel(analyzer), analyzer)
        sub = next(e for e in entries if e.handle == "mypkg.sub")
        assert sub.is_subpackage is True
        assert sub.file.name == "__init__.py"
        assert sub.file.parent.name == "sub"

    def test_pycache_and_data_excluded(self, analyzer: JediAnalyzer) -> None:
        # Neither the __pycache__ dir nor the data/ junk dir become children.
        entries = _enumerate_submodule_paths(_mypkg_sentinel(analyzer), analyzer)
        names = {e.file.name for e in entries} | {e.handle.rsplit(".", 1)[-1] for e in entries}
        assert "__pycache__" not in names
        assert "data" not in names

    def test_non_package_handle_returns_empty(self, analyzer: JediAnalyzer) -> None:
        # A plain module handle: _package_dirs returns [] → no children.
        plain = ModuleSentinel(_MYPKG / "alpha.py", "mypkg.alpha", analyzer)
        assert _enumerate_submodule_paths(plain, analyzer) == []

    def test_class_handle_returns_empty(self, analyzer: JediAnalyzer) -> None:
        # A class handle resolved through the real analyzer/Jedi → not a package.
        jedi_name = _find_jedi_name_for_handle(_A_HANDLE, analyzer)
        assert jedi_name is not None, f"Could not resolve handle {_A_HANDLE!r}"
        assert _enumerate_submodule_paths(jedi_name, analyzer) == []

    def test_none_handle_returns_empty(self, analyzer: JediAnalyzer) -> None:
        assert _enumerate_submodule_paths(None, analyzer) == []


class TestDirShallowQualifies:
    """The §3.5 one-level-capped importable-dir filter."""

    def test_dir_with_direct_py_qualifies(self) -> None:
        # sub/ contains gamma.py directly → qualifies.
        assert _dir_shallow_qualifies(_MYPKG / "sub") is True

    def test_data_dir_does_not_qualify(self) -> None:
        # data/ holds only notes.txt → junk, does not qualify.
        assert _dir_shallow_qualifies(_MYPKG / "data") is False

    def test_pycache_does_not_qualify(self) -> None:
        # __pycache__ holds only a .pyc → does not qualify (and is name-skipped
        # by the enumerator regardless).
        assert _dir_shallow_qualifies(_MYPKG / "__pycache__") is False


# ---------------------------------------------------------------------------
# Task 5 — resolve_submodules resolver + dir-stub contract + edge registration
# ---------------------------------------------------------------------------


class TestResolveSubmodules:
    """The ``submodules`` edge resolver wraps the enumerator as adjacents."""

    def test_handles_match_enumeration(self, analyzer: JediAnalyzer) -> None:
        result = resolve_submodules(_mypkg_sentinel(analyzer), analyzer)
        handles = {str(h) for h in result.handles}
        assert handles == {"mypkg.alpha", "mypkg.beta", "mypkg.sub"}

    def test_each_adjacent_carries_module_sentinel(self, analyzer: JediAnalyzer) -> None:
        # The children come from a pure dir scan (no Jedi Name) — each adjacent
        # carries a ModuleSentinel so build_stub needs no goto.
        result = resolve_submodules(_mypkg_sentinel(analyzer), analyzer)
        assert result.adjacents  # non-empty
        for _, name in result.adjacents:
            assert isinstance(name, ModuleSentinel)

    def test_unresolved_call_sites_absent(self, analyzer: JediAnalyzer) -> None:
        # submodules is not callees → the count notion does not apply.
        result = resolve_submodules(_mypkg_sentinel(analyzer), analyzer)
        assert result.unresolved_call_sites is None

    def test_non_package_returns_empty_not_none(self, analyzer: JediAnalyzer) -> None:
        # Wrong kind → measured-empty EdgeResult([]), never None.
        plain = ModuleSentinel(_MYPKG / "alpha.py", "mypkg.alpha", analyzer)
        result = resolve_submodules(plain, analyzer)
        assert result is not None
        assert result.adjacents == []


class TestEdgeRegistration:
    """``submodules`` is a first-class implemented edge."""

    def test_edge_status_implemented(self) -> None:
        assert edge_status("submodules") == "implemented"

    def test_in_resolver_registry(self) -> None:
        assert "submodules" in EDGE_RESOLVERS
        assert EDGE_RESOLVERS["submodules"] is resolve_submodules


class TestDirAnchoredStubContract:
    """A namespace-subpackage stub is dir-anchored and never byte-read (§3.6)."""

    def test_dir_sentinel_docstring_empty_no_raise(self, analyzer: JediAnalyzer) -> None:
        # A ModuleSentinel anchored on a directory returns "" (empty str, NOT
        # None) and does not raise.
        ds = ModuleSentinel(_MYPKG / "sub", "mypkg.sub", analyzer).docstring()
        assert ds == ""

    def test_dir_sentinel_never_reads_bytes(
        self, analyzer: JediAnalyzer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Guard: constructing a dir-anchored sentinel must not call read_text on
        # a directory.  Patch Path.read_text to fail loudly if it ever runs on a
        # path that is a directory.
        real_read_text = Path.read_text

        def _guarded_read_text(self: Path, *args: object, **kwargs: object) -> str:
            assert not self.is_dir(), f"byte read attempted on directory {self}"
            return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "read_text", _guarded_read_text)
        # A namespace-subpackage dir anchor: data/ is a non-package dir, but any
        # directory exercises the guard.  Use sub/ (a real dir under mypkg).
        sentinel = ModuleSentinel(_MYPKG / "sub", "mypkg.sub", analyzer)
        assert sentinel.docstring() == ""


class TestExpandTraceSmoke:
    """``submodules`` flows through expand/trace for free via registration."""

    @pytest.mark.asyncio
    async def test_expand_returns_child_stubs(self, analyzer: JediAnalyzer) -> None:
        result = await expand("mypkg", "submodules", analyzer)
        assert result.get("unsupported") is not True
        handles = {s["handle"] for s in result["stubs"]}
        assert handles == {"mypkg.alpha", "mypkg.beta", "mypkg.sub"}

    @pytest.mark.asyncio
    async def test_trace_one_hop_tree(self, analyzer: JediAnalyzer) -> None:
        result = await trace("mypkg", follow=["submodules"], analyzer=analyzer, max_depth=1)
        # The one-hop children appear as nodes reachable from the root.
        assert "mypkg.alpha" in result["nodes"]
        assert "mypkg.sub" in result["nodes"]


# ---------------------------------------------------------------------------
# Same-name file-vs-dir collision: deterministic CPython import precedence (#423
# review #6). A directory may hold both ``X.py`` and ``X/``; the winner must be
# precedence-decided (regular package > module > namespace package), NOT decided
# by arbitrary iterdir() order.
# ---------------------------------------------------------------------------

_COLLISION_PKG = _CONTAINMENT / "collision" / "pkg"


@pytest.fixture
def collision_analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the collision-fixture root."""
    return JediAnalyzer(str(_CONTAINMENT / "collision"))


def _collision_sentinel(analyzer: JediAnalyzer) -> ModuleSentinel:
    return ModuleSentinel(_COLLISION_PKG / "__init__.py", "pkg", analyzer)


class TestSubmoduleNameCollisionPrecedence:
    """A ``X.py``/``X/`` name clash resolves by CPython import precedence."""

    def test_regular_package_beats_same_name_module(self, collision_analyzer: JediAnalyzer) -> None:
        # regwins.py (module) AND regwins/__init__.py (regular pkg) → package wins.
        entries = _enumerate_submodule_paths(
            _collision_sentinel(collision_analyzer), collision_analyzer
        )
        regwins = next(e for e in entries if e.handle == "pkg.regwins")
        assert regwins.is_subpackage is True
        assert regwins.file.name == "__init__.py"
        assert regwins.file.parent.name == "regwins"

    def test_module_beats_same_name_namespace_dir(self, collision_analyzer: JediAnalyzer) -> None:
        # modwins.py (module) AND modwins/ (namespace dir, no __init__) → module wins.
        entries = _enumerate_submodule_paths(
            _collision_sentinel(collision_analyzer), collision_analyzer
        )
        modwins = next(e for e in entries if e.handle == "pkg.modwins")
        assert modwins.is_subpackage is False
        assert modwins.file.name == "modwins.py"

    def test_each_handle_appears_exactly_once(self, collision_analyzer: JediAnalyzer) -> None:
        entries = _enumerate_submodule_paths(
            _collision_sentinel(collision_analyzer), collision_analyzer
        )
        handles = [e.handle for e in entries]
        assert sorted(handles) == handles  # full-handle total order
        assert len(handles) == len(set(handles))  # no duplicate child handles
        assert {"pkg.regwins", "pkg.modwins"} <= set(handles)

    def test_winner_is_deterministic_across_runs(self, collision_analyzer: JediAnalyzer) -> None:
        # Independent of iterdir() order: repeated calls give identical results.
        first = _enumerate_submodule_paths(
            _collision_sentinel(collision_analyzer), collision_analyzer
        )
        second = _enumerate_submodule_paths(
            _collision_sentinel(collision_analyzer), collision_analyzer
        )
        assert [(e.handle, e.file.as_posix(), e.is_subpackage) for e in first] == [
            (e.handle, e.file.as_posix(), e.is_subpackage) for e in second
        ]
