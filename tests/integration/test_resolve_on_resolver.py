"""Regression: resolve and resolve_at run on the one resolver (#623 slice 3).

Before slice 3:

* ``resolve`` couldn't find external modules (``os``, ``io``, ``os.path``)
  that inspect / outline / expand / trace find (#602 part a);
* ``resolve_at`` fell back to Jedi's raw ``full_name`` as ``found: true``
  when canonicalization failed, handing out a handle no other tool accepts
  (audit row 3);
* a configured namespace package's symbols, and file-less namespace-package
  stubs, were scope ``external``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve, resolve_at
from pyeye.resolver import NotFound
from pyeye.scope import classify_scope
from tests.conformance.response_linter import lint_response


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


@pytest.fixture
def project(tmp_path: Path) -> tuple[JediAnalyzer, Path]:
    root = tmp_path / "proj"
    _write(
        root,
        {
            "pkg/__init__.py": "from pkg._impl import Thing\n",
            "pkg/_impl.py": "class Thing:\n    def method(self) -> int:\n        return 1\n",
            "main.py": "import logging\nimport nspkg\n\nlogging.getLogger\n",
            "nspkg/portion.py": "X = 1\n",
        },
    )
    return JediAnalyzer(str(root)), root


# ---------------------------------------------------------------------------
# #602 part a — resolve finds external modules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", ["os", "io", "logging", "os.path", "collections.abc"])
async def test_resolve_finds_an_external_module(project, module: str) -> None:
    analyzer, _ = project
    result = await resolve(module, analyzer)
    lint_response(result, "resolve")
    assert (result["found"], result["handle"], result["kind"], result["scope"]) == (
        True,
        module,
        "module",
        "external",
    )


@pytest.mark.parametrize(
    "handle", ["os", "logging", "pkg.Thing", "pkg._impl.Thing.method", "nspkg"]
)
async def test_resolve_and_inspect_agree(project, handle: str) -> None:
    analyzer, _ = project
    resolved = await resolve(handle, analyzer)
    node = await inspect(handle, analyzer)
    assert resolved["found"] is True and node["found"] is True
    for field in ("handle", "kind", "scope"):
        assert resolved[field] == node[field], (field, resolved, node)


# ---------------------------------------------------------------------------
# resolve_at
# ---------------------------------------------------------------------------


async def test_resolve_at_on_an_import_agrees_with_inspect(project) -> None:
    analyzer, root = project
    at = await resolve_at((root / "main.py").as_posix(), 1, 8, analyzer)  # `import logging`
    lint_response(at, "resolve_at")
    node = await inspect("logging", analyzer)
    assert (at["handle"], at["kind"], at["scope"]) == (node["handle"], node["kind"], node["scope"])


async def test_resolve_at_is_not_found_when_the_resolver_cannot_place_it(
    project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit row 3: no raw-``full_name`` fallback when canonicalization fails."""
    analyzer, root = project

    def miss(path: str, _analyzer: JediAnalyzer) -> NotFound:
        return NotFound(reason="unresolved", detail=f"{path!r} did not resolve.")

    # The operations package rebinds ``resolve`` to the function; patch the module.
    monkeypatch.setattr(sys.modules["pyeye.mcp.operations.resolve"], "resolve_handle", miss)
    at = await resolve_at((root / "main.py").as_posix(), 1, 8, analyzer)
    assert at["found"] is False
    assert at["reason"] == "unresolved"
    assert "handle" not in at or at.get("handle") != "logging"


# ---------------------------------------------------------------------------
# Scope: configured namespaces are project; site-packages stays external
# ---------------------------------------------------------------------------


async def test_configured_namespace_symbols_are_project(tmp_path: Path) -> None:
    """A configured namespace repo's modules resolve, and are project (#623 decision 7).

    Also a regression for #623 slice 2: the resolver treated ``acme`` as in the
    project but searched only the project's own roots for ``acme/tools.py``, so
    ``inspect("acme.tools.helper")`` was not found.
    """
    root = tmp_path / "proj"
    ns_repo = tmp_path / "ns-repo"
    _write(root, {"app.py": "from acme.tools import helper\n"})
    _write(ns_repo, {"acme/tools.py": "def helper() -> int:\n    return 1\n"})
    analyzer = JediAnalyzer(str(root), namespace_config={"acme": [ns_repo.as_posix()]})

    for handle, kind in (("acme.tools.helper", "function"), ("acme.tools", "module")):
        resolved = await resolve(handle, analyzer)
        node = await inspect(handle, analyzer)
        assert resolved["found"] is True and node["found"] is True, (resolved, node)
        assert (resolved["handle"], resolved["kind"]) == (handle, kind)
        assert resolved["scope"] == node["scope"] == "project"  # was "external" before slice 3


def test_site_packages_under_a_configured_root_stays_external(tmp_path: Path) -> None:
    """Widening SCOPE to namespace roots must not pull in an environment."""
    root = tmp_path / "proj"
    ns_repo = tmp_path / "ns-repo"
    (root).mkdir(parents=True)
    site = ns_repo / ".venv" / "lib" / "python3.12" / "site-packages" / "dep"
    site.mkdir(parents=True)
    (site / "mod.py").write_text("X = 1\n", encoding="utf-8")
    (ns_repo / "acme").mkdir()
    analyzer = JediAnalyzer(str(root), namespace_config={"acme": [ns_repo.as_posix()]})

    assert classify_scope(ns_repo / "acme" / "x.py", analyzer) == "project"
    assert classify_scope(site / "mod.py", analyzer) == "external"


async def test_namespace_package_stub_is_project(project) -> None:
    """A file-less PEP 420 stub from ``imports`` matches inspect (module / project)."""
    analyzer, _ = project
    result = await expand("main", "imports", analyzer)
    lint_response(result, "expand")
    stubs = {stub["handle"]: stub for stub in result["stubs"]}
    node = await inspect("nspkg", analyzer)
    assert (stubs["nspkg"]["kind"], stubs["nspkg"]["scope"]) == (node["kind"], node["scope"])
    assert stubs["nspkg"]["scope"] == "project"  # was "external" before #623 slice 3


@pytest.mark.skipif(os.name == "nt", reason="path layout assertion is POSIX-only")
async def test_resolve_dotted_alias_reports_the_canonical_handle(project) -> None:
    analyzer, root = project
    result = await resolve("pkg.Thing", analyzer)
    assert result["handle"] == "pkg._impl.Thing"
    assert Path(result["location"]["file"]) == root / "pkg" / "_impl.py"
