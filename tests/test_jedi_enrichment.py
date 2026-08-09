"""Tests for the JediAnalyzer._build_navigable_ref and _build_type_ref helpers."""

from pathlib import Path

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
    """_build_type_ref returns ref with inner_types for generic types like list[str]."""
    ref = await analyzer._build_type_ref("list[str]")

    assert ref is not None
    assert ref["name"] == "list[str]"
    assert ref["full_name"] is None
    assert ref["file"] is None
    assert ref["line"] is None
    # Should now have inner_types with resolved str
    assert ref.get("inner_types") is not None


@pytest.mark.asyncio
async def test_build_type_ref_union(analyzer: JediAnalyzer) -> None:
    """_build_type_ref returns ref with inner_types for union types like str | None."""
    ref = await analyzer._build_type_ref("str | None")

    assert ref is not None
    assert ref["name"] == "str | None"
    assert ref["full_name"] is None
    assert ref["file"] is None
    assert ref["line"] is None
    # Should now have inner_types
    assert ref.get("inner_types") is not None


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


# -- ClassVar / generic unwrapping tests -----------------------------------


@pytest.mark.asyncio
async def test_build_type_ref_classvar_resolves_inner(analyzer: JediAnalyzer) -> None:
    """ClassVar[ServiceConfig] should resolve ServiceConfig, not return partial."""
    ref = await analyzer._build_type_ref("ClassVar[ServiceConfig]")
    assert ref is not None
    assert ref["name"] == "ClassVar[ServiceConfig]"
    # The inner type should be resolved
    assert ref.get("inner_types") is not None
    inner = ref["inner_types"]
    assert len(inner) == 1
    assert inner[0]["name"] == "ServiceConfig"
    assert inner[0]["file"] is not None
    assert inner[0]["line"] is not None


@pytest.mark.asyncio
async def test_build_type_ref_optional_resolves_inner(analyzer: JediAnalyzer) -> None:
    """Optional[ServiceConfig] should resolve ServiceConfig as inner type."""
    ref = await analyzer._build_type_ref("Optional[ServiceConfig]")
    assert ref is not None
    assert ref.get("inner_types") is not None
    inner = ref["inner_types"]
    assert len(inner) == 1
    assert inner[0]["name"] == "ServiceConfig"
    assert inner[0]["file"] is not None


@pytest.mark.asyncio
async def test_build_type_ref_classvar_optional_nested(analyzer: JediAnalyzer) -> None:
    """ClassVar[Optional[ServiceConfig]] should unwrap recursively to ServiceConfig."""
    ref = await analyzer._build_type_ref("ClassVar[Optional[ServiceConfig]]")
    assert ref is not None
    assert ref.get("inner_types") is not None
    inner = ref["inner_types"]
    assert len(inner) == 1
    assert inner[0]["name"] == "ServiceConfig"
    assert inner[0]["file"] is not None


@pytest.mark.asyncio
async def test_build_type_ref_classvar_optional_list_nested(analyzer: JediAnalyzer) -> None:
    """ClassVar[Optional[List[ServiceConfig]]] should unwrap to ServiceConfig."""
    ref = await analyzer._build_type_ref("ClassVar[Optional[List[ServiceConfig]]]")
    assert ref is not None
    assert ref.get("inner_types") is not None
    inner = ref["inner_types"]
    assert len(inner) == 1
    assert inner[0]["name"] == "ServiceConfig"
    assert inner[0]["file"] is not None


@pytest.mark.asyncio
async def test_build_type_ref_dict_multi_arg(analyzer: JediAnalyzer) -> None:
    """dict[str, ServiceConfig] should resolve both inner types."""
    ref = await analyzer._build_type_ref("dict[str, ServiceConfig]")
    assert ref is not None
    assert ref.get("inner_types") is not None
    inner = ref["inner_types"]
    assert len(inner) == 2
    # str is a builtin
    assert inner[0]["name"] == "str"
    assert inner[0]["full_name"] == "builtins.str"
    # ServiceConfig is project-local
    assert inner[1]["name"] == "ServiceConfig"
    assert inner[1]["file"] is not None


@pytest.mark.asyncio
async def test_build_type_ref_list_builtin_inner(analyzer: JediAnalyzer) -> None:
    """list[str] should resolve str as inner type (builtin)."""
    ref = await analyzer._build_type_ref("list[str]")
    assert ref is not None
    assert ref["name"] == "list[str]"
    assert ref.get("inner_types") is not None
    inner = ref["inner_types"]
    assert len(inner) == 1
    assert inner[0]["name"] == "str"
    assert inner[0]["full_name"] == "builtins.str"


@pytest.mark.asyncio
async def test_build_type_ref_union_with_resolvable(analyzer: JediAnalyzer) -> None:
    """ServiceConfig | None should resolve ServiceConfig as inner type."""
    ref = await analyzer._build_type_ref("ServiceConfig | None")
    assert ref is not None
    assert ref.get("inner_types") is not None
    inner = ref["inner_types"]
    assert len(inner) == 2
    # One should be ServiceConfig (resolved)
    sc = [i for i in inner if i["name"] == "ServiceConfig"]
    assert len(sc) == 1
    assert sc[0]["file"] is not None
    # Other should be None (builtin)
    none_ref = [i for i in inner if i["name"] == "None"]
    assert len(none_ref) == 1
