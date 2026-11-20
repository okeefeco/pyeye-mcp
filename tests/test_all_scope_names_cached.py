"""A cached Script's all-scope names are read once, so its inference state stops growing (#1044).

Jedi's ``Script.get_names(all_scopes=True)`` builds fresh contexts for every
nested scope on each call, and Jedi's ``CachedMetaClass`` keys class values on
those contexts, so every call adds entries to the Script's ``memoize_cache``
that are never hit again (595 per call on django's
``tests/invalid_models_tests/test_models.py``). pyeye called it per request on
its long-lived cached Scripts (definition placement, the anchor lookup,
members), so a process doing thousands of resolves grew past 3 GB.

``file_artifact_cache.get_all_scope_names`` calls it once per cached Script and
hands back the same tuple of names for that Script's lifetime.
"""

from __future__ import annotations

import gc
from pathlib import Path

import jedi
import pytest

from pyeye import file_artifact_cache
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.file_artifact_cache import FileArtifactCache
from pyeye.mcp.operations.resolve import resolve, resolve_at

# The django shape that triggers it: a class defined inside a METHOD, with an
# assignment in its body (a TestCase method's local ``class Model: field = …``).
# Jedi builds a new class value for each such class on every all-scopes call; a
# class inside a plain function or at top level doesn't grow.
_NESTED = "class Cases:\n" + "".join(
    f"    def test_{i}(self):\n        class Local{i}:\n            x = {i}\n\n"
    f"        return Local{i}\n\n"
    for i in range(30)
)


def _class_line(i: int) -> int:
    """The line of ``class Local<i>`` in :data:`_NESTED` (its name starts at column 14)."""
    return 3 + 6 * i


def _memo_size(script: jedi.Script) -> int:
    return sum(len(v) for v in script._inference_state.memoize_cache.values())


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "cases.py").write_text(_NESTED, encoding="utf-8")
    return tmp_path


class TestTheCache:
    def test_the_same_names_come_back_for_one_script(self, project: Path) -> None:
        cache = FileArtifactCache()
        jedi_project = jedi.Project(project)
        path = project / "pkg" / "cases.py"

        first = cache.get_all_scope_names(path, jedi_project)
        second = cache.get_all_scope_names(path, jedi_project)

        assert isinstance(first, tuple)  # shared, so it can't be mutated
        assert first is second
        assert {n.name for n in first} >= {f"Local{i}" for i in range(30)}

    def test_reading_them_again_does_not_grow_the_inference_state(self, project: Path) -> None:
        cache = FileArtifactCache()
        jedi_project = jedi.Project(project)
        path = project / "pkg" / "cases.py"
        cache.get_all_scope_names(path, jedi_project)
        script = cache.get_script(path, jedi_project)
        warm = _memo_size(script)

        for _ in range(5):
            cache.get_all_scope_names(path, jedi_project)

        assert _memo_size(script) == warm

    def test_the_bug_it_avoids_is_real(self, project: Path) -> None:
        """Plain Jedi: every all-scopes ``get_names`` on one Script grows its memo."""
        path = project / "pkg" / "cases.py"
        script = jedi.Script(code=path.read_text(encoding="utf-8"), path=path)
        script.get_names(all_scopes=True, definitions=True, references=False)
        after_one = _memo_size(script)

        script.get_names(all_scopes=True, definitions=True, references=False)

        assert _memo_size(script) > after_one

    def test_an_edited_file_gets_new_names(self, project: Path) -> None:
        cache = FileArtifactCache()
        jedi_project = jedi.Project(project)
        path = project / "pkg" / "cases.py"
        before = cache.get_all_scope_names(path, jedi_project)

        path.write_text(_NESTED + "class Added:\n    pass\n", encoding="utf-8")

        after = cache.get_all_scope_names(path, jedi_project)
        assert after is not before
        assert "Added" in {n.name for n in after}

    def test_an_evicted_scripts_names_are_freed(self, project: Path) -> None:
        cache = FileArtifactCache(script_max_entries=1)
        jedi_project = jedi.Project(project)
        first, other = project / "pkg" / "cases.py", project / "pkg" / "__init__.py"
        cache.get_all_scope_names(first, jedi_project)
        assert len(cache._names_by_script) == 1

        cache.get_script(other, jedi_project)  # evicts the first Script
        gc.collect()

        assert len(cache._names_by_script) == 0

    def test_invalidation_drops_them(self, project: Path) -> None:
        cache = FileArtifactCache()
        jedi_project = jedi.Project(project)
        path = project / "pkg" / "cases.py"
        cache.get_all_scope_names(path, jedi_project)

        cache.invalidate_all()
        gc.collect()

        assert len(cache._names_by_script) == 0


class TestResolveNoLongerGrows:
    """The #1044 workload in miniature: repeated round trips on one file."""

    @pytest.mark.asyncio
    async def test_repeated_round_trips_keep_the_state_flat(self, project: Path) -> None:
        file_artifact_cache.invalidate_all()
        analyzer = JediAnalyzer(str(project))
        path = (project / "pkg" / "cases.py").as_posix()

        async def round_trip(i: int) -> None:
            at = await resolve_at(path, _class_line(i), 14, analyzer)
            assert at.get("found") is True, at
            await resolve(at["handle"], analyzer)

        for i in range(3):  # warm: every scope's values are built once
            await round_trip(i)
        script = file_artifact_cache.get_script(project / "pkg" / "cases.py", analyzer.project)
        warm = _memo_size(script)

        for i in range(3, 13):
            await round_trip(i)

        # Each new class's own inference adds a little; the all-scopes rebuild
        # (hundreds per call before #1044) must not come back.
        assert _memo_size(script) - warm < 10 * 20, (_memo_size(script), warm)


def test_only_the_cache_reads_all_scope_names() -> None:
    """A direct ``get_names(all_scopes=True)`` on a cached Script would bring #1044 back."""
    import ast as python_ast

    src = Path(__file__).resolve().parent.parent / "src" / "pyeye"
    offenders = []
    for path in sorted(src.rglob("*.py")):
        if path.name == "file_artifact_cache.py":
            continue
        for node in python_ast.walk(python_ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, python_ast.Call)
                and isinstance(node.func, python_ast.Attribute)
                and node.func.attr == "get_names"
                and any(
                    kw.arg == "all_scopes"
                    and not (isinstance(kw.value, python_ast.Constant) and kw.value.value is False)
                    for kw in node.keywords
                )
            ):
                offenders.append(f"{path.relative_to(src).as_posix()}:{node.lineno}")

    assert offenders == [], f"use file_artifact_cache.get_all_scope_names instead: {offenders}"
