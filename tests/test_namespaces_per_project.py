"""A project's analyzer sees only its own namespaces (#748).

``ProjectManager.get_analyzer`` merged every namespace registered on the
manager, by ANY project, into each new analyzer: a server that had served
project A (namespace ``shared``) gave project B's analyzer A's code. Namespace
registrations are now kept per project root.
"""

from __future__ import annotations

import ast
import importlib
import json
import logging
from pathlib import Path

import pytest

from pyeye.namespace_resolver import NamespaceResolver
from pyeye.project_manager import ProjectManager


def _project(root: Path, namespaces: dict[str, list[str]]) -> Path:
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    (root / ".pyeye.json").write_text(json.dumps({"namespaces": namespaces}))
    return root


def _ns_repo(root: Path, top: str, cls: str) -> Path:
    pkg = root / top / "lib"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(f"class {cls}:\n    pass\n")
    return root


@pytest.fixture
def two_projects(tmp_path: Path) -> tuple[Path, Path]:
    ns_a = _ns_repo(tmp_path / "ns_a", "alpha", "AlphaThing")
    ns_b = _ns_repo(tmp_path / "ns_b", "beta", "BetaThing")
    a = _project(tmp_path / "proj_a", {"alpha": [ns_a.as_posix()]})
    b = _project(tmp_path / "proj_b", {"beta": [ns_b.as_posix()]})
    return a, b


@pytest.fixture
def manager() -> ProjectManager:
    m = ProjectManager(max_projects=10)
    yield m  # type: ignore[misc]
    m.cleanup_all()


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["a", "b"])
async def test_two_projects_never_see_each_others_namespaces(
    two_projects: tuple[Path, Path], manager: ProjectManager, first: str
) -> None:
    a, b = two_projects
    order = [a, b] if first == "a" else [b, a]
    analyzers = {p: manager.get_analyzer(p.as_posix()) for p in order}

    assert set(analyzers[a].namespace_paths) == {"alpha"}
    assert set(analyzers[b].namespace_paths) == {"beta"}
    for project, other_ns in ((a, "ns_b"), (b, "ns_a")):
        searched = await analyzers[project]._resolve_scope_to_paths("all")
        assert not [p for p in searched if other_ns in p.parts], (project, searched)
        sys_path = [p.as_posix() for p in analyzers[project].added_sys_path]
        assert not [p for p in sys_path if f"/{other_ns}" in p]


def test_configure_packages_namespaces_reach_only_their_project(
    two_projects: tuple[Path, Path], manager: ProjectManager, tmp_path: Path
) -> None:
    """An unsaved (in-memory) registration still reaches its own project's analyzer."""
    a, b = two_projects
    extra = _ns_repo(tmp_path / "ns_extra", "gamma", "GammaThing")
    manager.namespace_resolver.register_namespace("gamma", [extra.as_posix()], project=a)

    assert "gamma" in manager.get_analyzer(a.as_posix()).namespace_paths
    assert "gamma" not in manager.get_analyzer(b.as_posix()).namespace_paths


def test_unscoped_registration_warns_with_the_namespace_and_applies_nowhere(
    two_projects: tuple[Path, Path], manager: ProjectManager, caplog: pytest.LogCaptureFixture
) -> None:
    a, _ = two_projects
    with caplog.at_level(logging.WARNING, logger="pyeye.namespace_resolver"):
        manager.namespace_resolver.register_namespace("orphan", [a.as_posix()])

    assert any("orphan" in r.getMessage() and "#748" in r.getMessage() for r in caplog.records)
    assert "orphan" not in manager.get_analyzer(a.as_posix()).namespace_paths


def test_namespaces_for_is_keyed_by_the_project_root(tmp_path: Path) -> None:
    resolver = NamespaceResolver()
    repo = tmp_path / "repo"
    repo.mkdir()
    resolver.register_namespace("ns", [repo.as_posix()], project=tmp_path / "x" / ".." / "p")

    assert set(resolver.namespaces_for(tmp_path / "p")) == {"ns"}
    assert resolver.namespaces_for(tmp_path / "q") == {}


def test_no_src_caller_registers_a_namespace_unscoped() -> None:
    """Every ``register_namespace`` call in ``src`` passes ``project=`` (#748)."""
    src = Path(importlib.import_module("pyeye").__file__).parent  # type: ignore[arg-type]
    unscoped = []
    for py in src.rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "register_namespace"
                and not any(k.arg == "project" for k in node.keywords)
            ):
                unscoped.append(f"{py.name}:{node.lineno}")
    assert unscoped == []
