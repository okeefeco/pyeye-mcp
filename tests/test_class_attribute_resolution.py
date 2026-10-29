"""Regression tests for #506: class-attribute handles resolve to the attribute itself.

Canonicalization and ``resolve`` split a handle at its last dot and treated
everything before it as a module. For ``module.Class.attr`` that "module" is a
class, so the lookup missed and fell through to synthetic-import ``infer()``.
``infer()`` answers "what value is this?": a method happens to infer to itself,
but an attribute infers to its value's type. So ``resolve`` reported
``Widget.name: str`` as ``builtins.str`` and ``Holder.factory = make_widget`` as
``make_widget``, with ``found: true``.

The external fallback also had no check that the inferred name was the one
requested, which is how ``collections.abc.Mapping`` resolved to
``typing._SpecialGenericAlias`` (#544).
"""

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.canonicalization import resolve_canonical
from pyeye.handle import Handle
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve

_FIXTURE = Path(__file__).parent / "fixtures" / "resolve_project"
_WIDGETS = _FIXTURE / "mypackage" / "_core" / "widgets.py"
_GUARDED = _FIXTURE / "mypackage" / "_core" / "guarded_imports_fixture.py"

# (handle, defining file, definition line), from the fixture source.
CLASS_ATTRIBUTES = [
    ("mypackage._core.widgets.Widget.name", _WIDGETS, 31),  # name: str = "default"
    ("mypackage._core.widgets.Widget.color", _WIDGETS, 29),  # color: ClassVar[str] = "blue"
    ("mypackage._core.widgets.Config.host", _WIDGETS, 68),  # host: str = "localhost"
    # Bound to a project function: infer() lands on make_widget, a real but wrong symbol.
    ("mypackage._core.guarded_imports_fixture.Holder.factory", _GUARDED, 67),
]


@pytest.fixture
def analyzer() -> JediAnalyzer:
    return JediAnalyzer(str(_FIXTURE))


class TestResolveCanonicalPlacesClassMembers:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("handle", "_file", "_line"), CLASS_ATTRIBUTES)
    async def test_class_attribute_is_its_own_canonical_handle(
        self, analyzer: JediAnalyzer, handle: str, _file: Path, _line: int
    ) -> None:
        assert await resolve_canonical(handle, analyzer) == Handle(handle)

    @pytest.mark.asyncio
    async def test_method_still_canonical(self, analyzer: JediAnalyzer) -> None:
        handle = "mypackage._core.widgets.Widget.greet"
        assert await resolve_canonical(handle, analyzer) == Handle(handle)

    @pytest.mark.asyncio
    async def test_member_through_reexported_class_collapses_to_definition(
        self, analyzer: JediAnalyzer
    ) -> None:
        """mypackage re-exports Widget, so mypackage.Widget.name is an alias path."""
        assert await resolve_canonical("mypackage.Widget.name", analyzer) == Handle(
            "mypackage._core.widgets.Widget.name"
        )

    @pytest.mark.asyncio
    async def test_unknown_member_is_none(self, analyzer: JediAnalyzer) -> None:
        assert await resolve_canonical("mypackage._core.widgets.Widget.nope", analyzer) is None


class TestResolveClassAttribute:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("handle", "file", "line"), CLASS_ATTRIBUTES)
    async def test_resolves_to_the_attribute_not_its_value(
        self, analyzer: JediAnalyzer, handle: str, file: Path, line: int
    ) -> None:
        result = await resolve(handle, analyzer)

        assert result["found"] is True
        assert result.get("handle") == handle, f"resolved to a different symbol: {result}"
        assert result["kind"] == "variable"
        assert result["scope"] == "project"
        assert Path(result["location"]["file"]) == file
        assert result["location"]["line_start"] == line

    @pytest.mark.asyncio
    async def test_alias_path_resolves_to_definition_site(self, analyzer: JediAnalyzer) -> None:
        result = await resolve("mypackage.Widget.name", analyzer)

        assert result.get("handle") == "mypackage._core.widgets.Widget.name"
        assert result["location"]["line_start"] == 31

    @pytest.mark.asyncio
    async def test_unknown_member_is_not_found(self, analyzer: JediAnalyzer) -> None:
        result = await resolve("mypackage._core.widgets.Widget.nope", analyzer)

        assert result == {"found": False, "reason": "unresolved"}


class TestInspectAgreesWithResolve:
    @pytest.mark.asyncio
    async def test_inspect_on_alias_path_finds_the_attribute(self, analyzer: JediAnalyzer) -> None:
        """Same contract as #431 for aliases: location and kind agree with the canonical handle."""
        alias_node = await inspect("mypackage.Widget.name", analyzer)
        canonical_node = await inspect("mypackage._core.widgets.Widget.name", analyzer)

        assert alias_node["found"] is True
        assert alias_node["kind"] == canonical_node["kind"] == "variable"
        assert alias_node["scope"] == "project"
        assert alias_node["location"] == canonical_node["location"]
        assert Path(alias_node["location"]["file"]) == _WIDGETS
        assert alias_node["location"]["line_start"] == 31


class TestExternalInferenceGuard:
    """An inferred definition is only an answer if it is the name that was asked for (#544)."""

    @pytest.mark.asyncio
    async def test_mapping_is_not_reported_as_its_typeshed_alias_type(
        self, analyzer: JediAnalyzer
    ) -> None:
        result = await resolve("collections.abc.Mapping", analyzer)

        assert result.get("handle") != "typing._SpecialGenericAlias"
        if result["found"]:
            assert result["handle"].rsplit(".", 1)[-1] == "Mapping"

    @pytest.mark.asyncio
    async def test_external_class_still_resolves(self, analyzer: JediAnalyzer) -> None:
        import json

        result = await resolve("json.JSONDecoder", analyzer)

        assert result["found"] is True
        assert result["handle"] == f"{json.JSONDecoder.__module__}.JSONDecoder"
        assert result["scope"] == "external"
