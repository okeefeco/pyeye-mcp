"""Regression tests for issue #429 — re-exported class FQN must resolve to its
definition site, never to the package ``__init__`` re-export line.

Background
----------
The handle→``Name`` lookup (now :func:`pyeye.resolver.resolve_handle`, #623)
places an FQN in the deepest module file it can find and accepts the ``Name``
whose ``full_name`` equals the handle. For a grouped re-export, the import
binding in a shallower ``__init__.py`` *also* reports ``full_name == handle``
(Jedi resolves the import one hop to the definition) and ``type == "class"``.
Whenever the definition module can't be found — simulated below — the deepest
module found is that ``__init__``, and the match is the import binding. The result is silently wrong: ``inspect`` reports ``members: 0,
superclasses: 0`` at the ``__init__`` line for a real class.

The fix anchors any match on its definition via ``goto`` (follow-through),
which is idempotent on a real definition and corrective on a re-export binding,
and rides the same deterministic ``goto`` path ``resolve_at`` uses.

Fixture layout (``tests/fixtures/reexport_grouped``)
----------------------------------------------------
``gp/sub/related.py`` — defines ``ForeignObject``, ``ForeignKey`` and
``OneToOneField`` (canonical definition site).
``gp/sub/__init__.py`` — re-exports them via a GROUPED, parenthesized import
(``from gp.sub.related import ( ... )``), each name on its own line — the
Django ``db/models/__init__.py`` pattern.

The definition module is simulated as "missing" by monkeypatching the
resolver's ``file_for_module`` to return ``None`` for it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from pyeye import resolver as resolver_mod
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect
from tests.utils.resolver_helpers import anchor_for

_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "reexport_grouped"

_HANDLE = "gp.sub.related.OneToOneField"
_DEFINITION_MODULE = "gp.sub.related"
_DEFINITION_FILE = "related.py"
_DEFINITION_LINE = 24  # ``class OneToOneField(ForeignKey):`` in the fixture

# Re-export *alias* path (issue #431): the public import path created by the
# grouped re-export in ``gp/sub/__init__.py``. ``resolve()`` accepts it and
# canonicalizes it to ``_HANDLE``; ``inspect``/``expand``/``trace``/``outline``
# must resolve it to the same definition site, not a not-found ``variable`` node.
_ALIAS = "gp.sub.OneToOneField"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the grouped re-export fixture."""
    return JediAnalyzer(str(_FIXTURE))


@pytest.fixture
def simulate_deepest_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the definition-module lookup to miss (stand-in for the #419 flake).

    The deepest module the resolver then finds is the shallower ``__init__``,
    whose grouped-import binding matches the handle's ``full_name``.
    """
    real_file_for_module = resolver_mod.file_for_module

    def fake_file_for_module(az: JediAnalyzer, module_dotted: str) -> Path | None:
        if module_dotted == _DEFINITION_MODULE:
            return None
        return real_file_for_module(az, module_dotted)

    monkeypatch.setattr(resolver_mod, "file_for_module", fake_file_for_module)


class TestReexportResolvesToDefinition:
    """#429 — the FQN must resolve to the class body, not the re-export line."""

    @pytest.mark.usefixtures("simulate_deepest_miss")
    def test_find_name_lands_on_definition_when_deepest_pass_misses(
        self, analyzer: JediAnalyzer
    ) -> None:
        """The resolved Jedi Name must point at the class definition file/line.

        Without the fix, the fall-through returns the ``__init__`` import
        binding (``__init__.py`` at the grouped-import line) instead.
        """
        name = anchor_for(_HANDLE, analyzer)

        assert name is not None
        assert name.module_path is not None
        assert name.module_path.name == _DEFINITION_FILE
        assert name.line == _DEFINITION_LINE

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("simulate_deepest_miss")
    async def test_inspect_reports_real_members_when_deepest_pass_misses(
        self, analyzer: JediAnalyzer
    ) -> None:
        """inspect must report the class's real members/superclasses, not 0/0.

        ``members: 0`` at the ``__init__`` line is the exact silent-wrong
        symptom reported in #429.
        """
        node = await inspect(_HANDLE, analyzer)

        assert node["kind"] == "class"
        assert node["location"]["file"].endswith(_DEFINITION_FILE)
        assert node["location"]["line_start"] == _DEFINITION_LINE
        # OneToOneField has 2 methods + 1 attribute; ForeignKey base.
        assert node["edge_counts"].get("members", 0) > 0
        assert node["edge_counts"].get("superclasses", 0) == 1

    @pytest.mark.asyncio
    async def test_inspect_agrees_with_resolve_at(self, analyzer: JediAnalyzer) -> None:
        """Acceptance criterion #2: inspect(handle) and resolve_at(def) agree.

        Entry points must not be entry-point-dependent: the FQN handle and a
        position on the definition line must resolve to the same location.
        """
        from pyeye.mcp.operations.resolve import resolve_at

        node = await inspect(_HANDLE, analyzer)

        def_file = _FIXTURE / "gp" / "sub" / _DEFINITION_FILE
        at = await resolve_at(str(def_file), _DEFINITION_LINE, 6, analyzer)

        assert at["found"] is True
        at_location = cast(dict[str, Any], at)["location"]
        assert node["location"]["file"] == at_location["file"]
        assert node["location"]["line_start"] == at_location["line_start"]

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("simulate_deepest_miss")
    async def test_inspect_agrees_with_resolve_at_when_deepest_pass_misses(
        self, analyzer: JediAnalyzer
    ) -> None:
        """Criterion #2 must hold on the path that actually broke.

        The plain agreement check passes even without the fix, because the
        deepest-module pass normally matches the definition directly. Forcing
        that pass to miss (the #419 fall-through) is the only path where the
        unfixed walk lands ``inspect`` on the ``__init__`` re-export line while
        ``resolve_at`` (position-based) stays on the definition — so this is the
        case where FQN-string and position resolution would *disagree*.
        """
        from pyeye.mcp.operations.resolve import resolve_at

        node = await inspect(_HANDLE, analyzer)

        def_file = _FIXTURE / "gp" / "sub" / _DEFINITION_FILE
        at = await resolve_at(str(def_file), _DEFINITION_LINE, 6, analyzer)

        assert at["found"] is True
        at_location = cast(dict[str, Any], at)["location"]
        assert node["location"]["file"] == at_location["file"]
        assert node["location"]["line_start"] == at_location["line_start"]


class _FakeTarget:
    def __init__(self, full_name: str | None, module_path: Path | None) -> None:
        self.full_name = full_name
        self.module_path = module_path


class _FakeName:
    """Minimal Jedi-Name stand-in for unit-testing ``resolver._anchor_on_definition``."""

    def __init__(self, goto_result: Any) -> None:
        self._goto_result = goto_result

    def goto(self, **kwargs: Any) -> Any:  # noqa: ARG002 - test double swallows goto kwargs
        if isinstance(self._goto_result, Exception):
            raise self._goto_result
        return self._goto_result


class TestAnchorOnDefinitionFallbacks:
    """Defensive branches of the follow-through helper (issue #429)."""

    def test_returns_original_when_goto_raises(self) -> None:
        """If ``goto`` raises, keep the original matched name (never crash)."""
        from pyeye.resolver import _anchor_on_definition

        name = _FakeName(RuntimeError("jedi blew up"))
        assert _anchor_on_definition(name, _HANDLE) is name

    def test_returns_original_when_no_target_matches_handle(self) -> None:
        """If no goto target matches the handle, keep the original name.

        Guards against ``goto`` wandering to an unrelated symbol — a genuine
        definition must not be discarded for a worse one.
        """
        from pyeye.resolver import _anchor_on_definition

        wrong = _FakeTarget(full_name="some.other.Symbol", module_path=Path("x.py"))
        no_path = _FakeTarget(full_name=_HANDLE, module_path=None)
        name = _FakeName([wrong, no_path])
        assert _anchor_on_definition(name, _HANDLE) is name

    def test_returns_definition_target_when_it_matches(self) -> None:
        """The matching, located target replaces the original (the repair)."""
        from pyeye.resolver import _anchor_on_definition

        target = _FakeTarget(full_name=_HANDLE, module_path=Path("related.py"))
        name = _FakeName([target])
        assert _anchor_on_definition(name, _HANDLE) is target


class TestAliasResolvesToDefinition:
    """#431 — a re-export *alias* FQN must resolve to the definition, not 404.

    Distinct from #429: the alias never matches any ``full_name`` (Jedi reports
    the binding's ``full_name`` as the canonical handle, not the alias string),
    so the handle->Name walk misses entirely and ``inspect`` emits its minimal
    ``kind: variable`` fallback. The fix canonicalizes the input on a miss.
    """

    @pytest.mark.asyncio
    async def test_inspect_alias_resolves_to_class_definition(self, analyzer: JediAnalyzer) -> None:
        """inspect(alias) must report the class at its definition site, not 404."""
        node = await inspect(_ALIAS, analyzer)

        assert node["kind"] == "class"
        assert node["location"]["file"].endswith(_DEFINITION_FILE)
        assert node["location"]["line_start"] == _DEFINITION_LINE
        assert node["edge_counts"].get("members", 0) > 0
        assert node["edge_counts"].get("superclasses", 0) == 1

    @pytest.mark.asyncio
    async def test_inspect_alias_agrees_with_canonical_and_resolve_at(
        self, analyzer: JediAnalyzer
    ) -> None:
        """Acceptance #2: inspect(alias) == inspect(canonical) == resolve_at(def)."""
        from pyeye.mcp.operations.resolve import resolve_at

        alias_node = await inspect(_ALIAS, analyzer)
        canon_node = await inspect(_HANDLE, analyzer)

        def_file = _FIXTURE / "gp" / "sub" / _DEFINITION_FILE
        at = await resolve_at(str(def_file), _DEFINITION_LINE, 6, analyzer)
        assert at["found"] is True
        at_location = cast(dict[str, Any], at)["location"]

        assert alias_node["location"]["file"] == canon_node["location"]["file"]
        assert alias_node["location"]["line_start"] == canon_node["location"]["line_start"]
        assert alias_node["location"]["file"] == at_location["file"]
        assert alias_node["location"]["line_start"] == at_location["line_start"]

    @pytest.mark.asyncio
    async def test_expand_alias_resolves_superclasses(self, analyzer: JediAnalyzer) -> None:
        """expand(alias, 'superclasses') must resolve via the same path (not empty)."""
        from pyeye.mcp.operations.expand import expand

        result = await expand(_ALIAS, "superclasses", analyzer)
        bases = [s.get("handle") for s in result.get("stubs", [])]
        assert "gp.sub.related.ForeignKey" in bases

    @pytest.mark.asyncio
    async def test_outline_alias_resolves_to_class(self, analyzer: JediAnalyzer) -> None:
        """outline(alias) must produce the class node, not a not-found stub."""
        from pyeye.mcp.operations.outline import outline

        result = await outline(_ALIAS, analyzer)
        assert result["node"]["kind"] == "class"
        assert result["node"]["line_start"] == _DEFINITION_LINE
