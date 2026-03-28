"""Tests for JediAnalyzer._build_navigable_ref, _build_type_ref, and _enrich_method helpers."""

from pathlib import Path

import jedi
import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "lookup_project"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """Return a JediAnalyzer pointed at the lookup_project fixture."""
    return JediAnalyzer(str(FIXTURE_PATH))


# ---------------------------------------------------------------------------
# _build_navigable_ref
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_navigable_ref_with_normal_jedi_name(analyzer: JediAnalyzer) -> None:
    """_build_navigable_ref returns expected fields for a real Jedi Name."""
    results = await analyzer._search_all_scopes("ServiceManager")
    assert results, "Expected at least one result for ServiceManager"

    name_obj = results[0]
    ref = analyzer._build_navigable_ref(name_obj)

    assert ref["name"] == "ServiceManager"
    assert ref["full_name"] is not None
    assert "ServiceManager" in ref["full_name"]
    assert ref["file"] is not None
    assert ref["file"].endswith("models.py")
    assert ref["line"] is not None
    assert isinstance(ref["line"], int)


@pytest.mark.asyncio
async def test_build_navigable_ref_posix_path(analyzer: JediAnalyzer) -> None:
    """_build_navigable_ref always returns POSIX paths (no backslashes)."""
    results = await analyzer._search_all_scopes("ServiceManager")
    assert results

    ref = analyzer._build_navigable_ref(results[0])

    assert ref["file"] is not None
    assert "\\" not in ref["file"], "File path must use forward slashes (POSIX)"


# ---------------------------------------------------------------------------
# _build_type_ref
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_type_ref_project_local_class(analyzer: JediAnalyzer) -> None:
    """_build_type_ref resolves a project-local class to its definition."""
    ref = await analyzer._build_type_ref("ServiceConfig")

    assert ref is not None
    assert ref["name"] == "ServiceConfig"
    assert ref["full_name"] is not None
    assert "ServiceConfig" in ref["full_name"]
    assert ref["file"] is not None
    assert ref["file"].endswith("models.py")
    assert ref["line"] is not None
    assert isinstance(ref["line"], int)


@pytest.mark.asyncio
async def test_build_type_ref_builtin(analyzer: JediAnalyzer) -> None:
    """_build_type_ref returns builtins.X full_name with no file for builtins."""
    ref = await analyzer._build_type_ref("int")

    assert ref is not None
    assert ref["name"] == "int"
    assert ref["full_name"] == "builtins.int"
    assert ref["file"] is None
    assert ref["line"] is None


@pytest.mark.asyncio
async def test_build_type_ref_generic(analyzer: JediAnalyzer) -> None:
    """_build_type_ref returns a partial ref for generic types like list[str]."""
    ref = await analyzer._build_type_ref("list[str]")

    assert ref is not None
    assert ref["name"] == "list[str]"
    assert ref["full_name"] is None
    assert ref["file"] is None
    assert ref["line"] is None


@pytest.mark.asyncio
async def test_build_type_ref_union(analyzer: JediAnalyzer) -> None:
    """_build_type_ref returns a partial ref for union types like str | None."""
    ref = await analyzer._build_type_ref("str | None")

    assert ref is not None
    assert ref["name"] == "str | None"
    assert ref["full_name"] is None
    assert ref["file"] is None
    assert ref["line"] is None


@pytest.mark.asyncio
async def test_build_type_ref_none_input(analyzer: JediAnalyzer) -> None:
    """_build_type_ref returns None when given None."""
    result = await analyzer._build_type_ref(None)
    assert result is None


@pytest.mark.asyncio
async def test_build_type_ref_empty_string(analyzer: JediAnalyzer) -> None:
    """_build_type_ref returns None when given an empty string."""
    result = await analyzer._build_type_ref("")
    assert result is None


# ---------------------------------------------------------------------------
# Helpers for _enrich_method tests
# ---------------------------------------------------------------------------


async def _get_method_name(
    analyzer: JediAnalyzer, method: str, full_name_fragment: str | None = None
) -> jedi.api.classes.Name:
    """Search for a method Name object via _search_all_scopes and filter by full_name."""
    results = await analyzer._search_all_scopes(method)
    if full_name_fragment is not None:
        results = [r for r in results if full_name_fragment in (r.full_name or "")]
    assert results, f"No results for method {method!r} (fragment={full_name_fragment!r})"
    return results[0]


def _get_init_from_script(
    analyzer: JediAnalyzer, file_path: Path, full_name_fragment: str
) -> jedi.api.classes.Name:
    """Return a __init__ Name object from a Jedi Script, filtered by full_name."""
    source = file_path.read_text()
    script = jedi.Script(source, path=str(file_path), project=analyzer.project)
    names = script.get_names(all_scopes=True)
    matching = [
        n
        for n in names
        if n.name == "__init__"
        and n.type == "function"
        and full_name_fragment in (n.full_name or "")
    ]
    assert matching, f"No __init__ found with fragment {full_name_fragment!r}"
    return matching[0]


# ---------------------------------------------------------------------------
# _enrich_method
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_method_typed_params_and_defaults(analyzer: JediAnalyzer) -> None:
    """_enrich_method for ServiceManager.start returns correct signature, return type, and params."""
    name_obj = await _get_method_name(analyzer, "start", "ServiceManager.start")
    result = await analyzer._enrich_method(name_obj)

    assert result["name"] == "start"
    assert result["full_name"] is not None
    assert "ServiceManager.start" in result["full_name"]
    assert result["file"] is not None
    assert result["file"].endswith("models.py")
    assert "\\" not in result["file"], "File must use POSIX path"
    assert result["line"] == 34

    # Signature should include param with type and default
    assert result["signature"] is not None
    assert "port: int" in result["signature"]
    assert "8080" in result["signature"]
    assert "-> bool" in result["signature"]

    # Return type: bool (builtin)
    rt = result["return_type"]
    assert rt is not None
    assert rt["name"] == "bool"
    assert rt["full_name"] == "builtins.bool"
    assert rt["file"] is None
    assert rt["line"] is None

    # Parameters: self (no type_hint, no default), port (typed, with default)
    params = result["parameters"]
    assert len(params) == 2

    self_param = params[0]
    assert self_param["name"] == "self"
    assert self_param["type_hint"] is None
    assert self_param["default"] is None

    port_param = params[1]
    assert port_param["name"] == "port"
    assert port_param["type_hint"] is not None
    assert port_param["type_hint"]["name"] == "int"
    assert port_param["type_hint"]["full_name"] == "builtins.int"
    assert port_param["default"] == "8080"


@pytest.mark.asyncio
async def test_enrich_method_no_annotations(analyzer: JediAnalyzer) -> None:
    """_enrich_method for helper() returns null type_hints, correct defaults."""
    name_obj = await _get_method_name(analyzer, "helper")
    result = await analyzer._enrich_method(name_obj)

    assert result["name"] == "helper"
    assert result["file"] is not None
    assert result["file"].endswith("utils.py")

    # No return type annotation → no return type
    assert result["return_type"] is None

    params = result["parameters"]
    assert len(params) == 2

    x_param = params[0]
    assert x_param["name"] == "x"
    assert x_param["type_hint"] is None
    assert x_param["default"] is None

    y_param = params[1]
    assert y_param["name"] == "y"
    assert y_param["type_hint"] is None, "y has no source annotation — type_hint must be null"
    assert y_param["default"] == "10"


@pytest.mark.asyncio
async def test_enrich_method_return_type_project_local_class(analyzer: JediAnalyzer) -> None:
    """_enrich_method for get_config resolves return type to ServiceConfig with file+line."""
    name_obj = await _get_method_name(analyzer, "get_config", "ServiceManager.get_config")
    result = await analyzer._enrich_method(name_obj)

    assert result["name"] == "get_config"

    rt = result["return_type"]
    assert rt is not None
    assert rt["name"] == "ServiceConfig"
    assert rt["full_name"] is not None
    assert "ServiceConfig" in rt["full_name"]
    assert rt["file"] is not None
    assert rt["file"].endswith("models.py")
    assert "\\" not in rt["file"]
    assert isinstance(rt["line"], int)


@pytest.mark.asyncio
async def test_enrich_method_init_self_and_typed_params(analyzer: JediAnalyzer) -> None:
    """_enrich_method for ServiceManager.__init__ handles self, ServiceConfig param, str param."""
    name_obj = _get_init_from_script(
        analyzer,
        FIXTURE_PATH / "models.py",
        "ServiceManager.__init__",
    )
    result = await analyzer._enrich_method(name_obj)

    assert result["name"] == "__init__"
    assert result["file"] is not None
    assert result["file"].endswith("models.py")

    params = result["parameters"]
    assert len(params) == 3

    # self: no type hint, no default
    self_param = params[0]
    assert self_param["name"] == "self"
    assert self_param["type_hint"] is None
    assert self_param["default"] is None

    # config: typed as ServiceConfig (project-local), no default
    config_param = params[1]
    assert config_param["name"] == "config"
    assert config_param["type_hint"] is not None
    assert config_param["type_hint"]["name"] == "ServiceConfig"
    assert config_param["type_hint"]["file"] is not None
    assert config_param["type_hint"]["file"].endswith("models.py")
    assert isinstance(config_param["type_hint"]["line"], int)
    assert config_param["default"] is None

    # name: typed as str, default "default"
    name_param = params[2]
    assert name_param["name"] == "name"
    assert name_param["type_hint"] is not None
    assert name_param["type_hint"]["name"] == "str"
    assert name_param["type_hint"]["full_name"] == "builtins.str"
    assert name_param["default"] == '"default"'
