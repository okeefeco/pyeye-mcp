"""A namespace package's ``__init__.pyi`` declares its members, as Jedi reads it (#1004).

A directory with ``__init__.pyi`` and no ``__init__.py`` is a PEP 420 namespace
package at runtime, and Jedi treats it so (``type == "namespace"``), while
merging each portion's ``__init__.pyi`` declarations into it and keeping every
portion's submodules. pyeye had two gaps against that:

- a stub-only package (``__init__.pyi`` and ``.pyi`` modules only) didn't
  qualify as a namespace at all, so ``resolve("stubpkg")`` was unresolved,
  while ``enclosing_scope`` of ``stubpkg.X`` emitted it: a round-trip break;
- a namespace's ``members`` ignored its portions' ``__init__.pyi`` (a FALSE
  measured zero), and ``pkg.M`` declared there didn't resolve.

No package changes classification: these stay namespace packages, anchored at
their directory, and only nodes located at a ``.pyi`` carry ``stub: true``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve
from pyeye.project_manager import ProjectManager
from tests.conformance.response_linter import lint_response


@pytest.fixture
def analyzer(tmp_path: Path):  # type: ignore[no-untyped-def]
    proj = tmp_path / "proj"
    files = {
        # stub-only package: stubs only
        "stubpkg/__init__.pyi": "class X: ...\n",
        "stubpkg/sub.pyi": "def f() -> int: ...\n",
        # __init__.pyi beside .py submodules
        "mixed/__init__.pyi": "class M: ...\n",
        "mixed/mod.py": "def g():\n    return 1\n",
        # a regular package with a stub beside its __init__.py: unchanged
        "regular/__init__.py": "class R:\n    pass\n",
        "regular/__init__.pyi": "class R: ...\n",
        "app/__init__.py": "",
    }
    for rel, text in files.items():
        (proj / rel).parent.mkdir(parents=True, exist_ok=True)
        (proj / rel).write_text(text, encoding="utf-8")
    repo_a, repo_b = tmp_path / "repoA", tmp_path / "repoB"
    (repo_a / "acme").mkdir(parents=True)
    (repo_a / "acme" / "__init__.pyi").write_text("class Shared: ...\nclass OnlyA: ...\n")
    (repo_a / "acme" / "tools.py").write_text("def a():\n    pass\n")
    (repo_b / "acme").mkdir(parents=True)
    (repo_b / "acme" / "__init__.pyi").write_text("class Shared: ...\nclass B: ...\n")
    (repo_b / "acme" / "more.py").write_text("def b():\n    pass\n")
    (proj / ".pyeye.json").write_text(
        json.dumps({"namespaces": {"acme": [repo_a.as_posix(), repo_b.as_posix()]}})
    )
    manager = ProjectManager(max_projects=4)
    yield manager.get_analyzer(proj.as_posix())
    manager.cleanup_all()


def _file(result: dict) -> str:
    return result["location"]["file"]


@pytest.mark.asyncio
async def test_a_stub_only_package_resolves_as_a_namespace(analyzer) -> None:  # type: ignore[no-untyped-def]
    result = await resolve("stubpkg", analyzer)

    assert result["found"] is True and result["kind"] == "module"
    assert Path(_file(result)).is_dir()  # anchored at its directory (#444)
    assert "stub" not in result  # no single definition file: not a stub node
    lint_response(result, "resolve")


@pytest.mark.asyncio
async def test_its_members_enclosing_scope_round_trips(analyzer) -> None:  # type: ignore[no-untyped-def]
    result = await expand("stubpkg.X", "enclosing_scope", analyzer)

    assert [s["handle"] for s in result["stubs"]] == ["stubpkg"]
    assert "stub" not in result["stubs"][0]  # the package node, not a .pyi node
    assert (await resolve("stubpkg", analyzer))["found"] is True  # round trip
    lint_response(result, "expand")


@pytest.mark.asyncio
async def test_its_submodules_include_stub_modules(analyzer) -> None:  # type: ignore[no-untyped-def]
    result = await expand("stubpkg", "submodules", analyzer)

    assert [s["handle"] for s in result["stubs"]] == ["stubpkg.sub"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("package", "member"), [("stubpkg", "X"), ("mixed", "M")])
async def test_the_stubs_declarations_are_members(analyzer, package: str, member: str) -> None:  # type: ignore[no-untyped-def]
    """Was a false measured zero: members [] for a stub that declares names."""
    members = await expand(package, "members", analyzer)
    assert [s["handle"] for s in members["stubs"]] == [f"{package}.{member}"]
    assert members["stubs"][0]["stub"] is True  # located at the __init__.pyi

    node = await inspect(package, analyzer)
    assert node["edge_counts"]["members"] == 1
    lint_response(members, "expand")


@pytest.mark.asyncio
async def test_a_declaration_resolves_and_inspects_at_the_stub(analyzer) -> None:  # type: ignore[no-untyped-def]
    result = await resolve("mixed.M", analyzer)
    assert result["found"] is True and result["kind"] == "class"
    assert Path(_file(result)).name == "__init__.pyi" and result["stub"] is True
    lint_response(result, "resolve")

    node = await inspect("mixed.M", analyzer)
    assert node["kind"] == "class" and node["stub"] is True

    scope = await expand("mixed.M", "enclosing_scope", analyzer)
    assert [s["handle"] for s in scope["stubs"]] == ["mixed"]


@pytest.mark.asyncio
async def test_the_mixed_package_keeps_its_source_submodules(analyzer) -> None:  # type: ignore[no-untyped-def]
    result = await resolve("mixed.mod", analyzer)
    assert result["found"] is True and Path(_file(result)).name == "mod.py"
    assert "stub" not in result


@pytest.mark.asyncio
async def test_a_namespace_keeps_every_portion(analyzer) -> None:  # type: ignore[no-untyped-def]
    """A portion holding __init__.pyi is still a portion: nothing is reclassified."""
    submodules = await expand("acme", "submodules", analyzer)
    assert {s["handle"] for s in submodules["stubs"]} == {"acme.tools", "acme.more"}
    for handle in ("acme.OnlyA", "acme.B", "acme.tools", "acme.more"):
        assert (await resolve(handle, analyzer))["found"] is True, handle


@pytest.mark.asyncio
async def test_a_name_two_portions_declare_comes_from_the_first(analyzer) -> None:  # type: ignore[no-untyped-def]
    """Portion order is sys.path order: the first portion's declaration wins, once."""
    members = await expand("acme", "members", analyzer)
    handles = [s["handle"] for s in members["stubs"]]
    assert handles.count("acme.Shared") == 1
    assert set(handles) == {"acme.Shared", "acme.OnlyA", "acme.B"}

    shared = await resolve("acme.Shared", analyzer)
    assert shared["found"] is True and "repoA" in _file(shared)


@pytest.mark.asyncio
async def test_a_regular_package_with_a_stub_is_unchanged(analyzer) -> None:  # type: ignore[no-untyped-def]
    result = await resolve("regular", analyzer)
    assert result["found"] is True and Path(_file(result)).name == "__init__.py"
    assert "stub" not in result


@pytest.mark.asyncio
async def test_a_portions_stub_file_resolves_as_its_package(analyzer) -> None:  # type: ignore[no-untyped-def]
    """The file form of ``mixed/__init__.pyi`` is the package, at its directory (Check D.2)."""
    stub = Path(analyzer.project_path) / "mixed" / "__init__.pyi"
    by_file = await resolve(stub.as_posix(), analyzer)
    by_name = await resolve("mixed", analyzer)

    assert by_file == by_name and "stub" not in by_file
    lint_response(by_file, "resolve")
