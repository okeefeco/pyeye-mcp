"""Regression tests for issue #429 — re-exported class FQN must resolve to its
definition site, never to the package ``__init__`` re-export line.

Background
----------
``_find_jedi_name_for_handle`` maps an FQN handle back to a Jedi ``Name`` by
walking progressively shorter module paths and accepting the first ``Name``
whose ``full_name`` equals the handle. The deepest (definition) module is tried
first, so this is *usually* correct. But for a grouped re-export, the import
binding in a shallower ``__init__.py`` *also* reports ``full_name == handle``
(Jedi resolves the import one hop to the definition) and ``type == "class"``.
Whenever the deepest-module pass fails to yield a match — the #419-class Jedi
``full_name`` non-determinism — the loop falls through and returns that import
binding. The result is silently wrong: ``inspect`` reports ``members: 0,
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

The deepest-module pass is simulated as "missing" by monkeypatching
``find_module_file`` to return ``None`` for the definition module — the
deterministic stand-in for the #419 flake that triggers the fall-through.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import _find_jedi_name_for_handle, inspect

# NOTE: fetch the *module* via ``sys.modules`` — the ``operations`` package
# ``__init__`` does ``from .inspect import inspect``, which rebinds the
# ``inspect`` attribute to the *function*, so any attribute-based import
# (``from ...operations import inspect`` or ``import ...operations.inspect``)
# yields the function, not the module. Monkeypatching needs the real module.
inspect_ops = sys.modules["pyeye.mcp.operations.inspect"]

_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "reexport_grouped"

_HANDLE = "gp.sub.related.OneToOneField"
_DEFINITION_MODULE = "gp.sub.related"
_DEFINITION_FILE = "related.py"
_DEFINITION_LINE = 24  # ``class OneToOneField(ForeignKey):`` in the fixture


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the grouped re-export fixture."""
    return JediAnalyzer(str(_FIXTURE))


@pytest.fixture
def simulate_deepest_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the definition-module lookup to miss (stand-in for the #419 flake).

    Mirrors the production trigger: the deepest (definition) module pass fails
    to yield a ``full_name`` match, so ``_find_jedi_name_for_handle`` falls
    through to the shallower ``__init__`` whose grouped-import binding matches.
    """
    real_find_module_file = inspect_ops.find_module_file

    def fake_find_module_file(module_dotted: str, az: JediAnalyzer) -> Path | None:
        if module_dotted == _DEFINITION_MODULE:
            return None
        return real_find_module_file(module_dotted, az)

    monkeypatch.setattr(inspect_ops, "find_module_file", fake_find_module_file)


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
        name = _find_jedi_name_for_handle(_HANDLE, analyzer)

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
    """Minimal Jedi-Name stand-in for unit-testing ``_anchor_on_definition``."""

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
        from pyeye.mcp.operations.inspect import _anchor_on_definition

        name = _FakeName(RuntimeError("jedi blew up"))
        assert _anchor_on_definition(name, _HANDLE) is name

    def test_returns_original_when_no_target_matches_handle(self) -> None:
        """If no goto target matches the handle, keep the original name.

        Guards against ``goto`` wandering to an unrelated symbol — a genuine
        definition must not be discarded for a worse one.
        """
        from pyeye.mcp.operations.inspect import _anchor_on_definition

        wrong = _FakeTarget(full_name="some.other.Symbol", module_path=Path("x.py"))
        no_path = _FakeTarget(full_name=_HANDLE, module_path=None)
        name = _FakeName([wrong, no_path])
        assert _anchor_on_definition(name, _HANDLE) is name

    def test_returns_definition_target_when_it_matches(self) -> None:
        """The matching, located target replaces the original (the repair)."""
        from pyeye.mcp.operations.inspect import _anchor_on_definition

        target = _FakeTarget(full_name=_HANDLE, module_path=Path("related.py"))
        name = _FakeName([target])
        assert _anchor_on_definition(name, _HANDLE) is target
