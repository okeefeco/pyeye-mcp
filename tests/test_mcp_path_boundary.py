"""Every file path an MCP tool returns is absolute, forward-slash and ``..``-free (#717).

Agents feed these paths straight back to their file tools on every platform, so
the response boundary is where the "display and pass paths as POSIX" rule has to
hold, whatever spelling the project was opened with. The walker is style-free:
it checks the values, not how the code built them.

Path-bearing keys were found by sweeping every core tool over the cross-tool
corpora: ``file`` / ``config_file`` strings, the ``packages`` and
``unresolved_importers`` lists, ``namespaces`` (name -> list of paths), and
``standalone.dirs``. ``report_issues`` is a URL and is not a path.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from pyeye.mcp import server
from pyeye.mcp.operations.edges import EDGE_RESOLVERS
from tests.test_cross_tool_invariants import _EXTRA_SEEDS, _SWEEP_CORPORA, _module_seeds
from tests.test_plugin_envelope import (
    ALL_TOOLS,
    EXTRA_ARGS,
    _config,
    _plugins,
    _wrapped_server,
)

_PATH_KEYS = frozenset({"file", "config_file"})
_PATH_LIST_KEYS = frozenset({"packages", "unresolved_importers", "dirs"})
_DRIVE = re.compile(r"^[A-Za-z]:/")

#: corpus name -> (directory copied into tmp, root relative to that copy)
_CORPORA: dict[str, tuple[Path, str]] = {
    "cross_tool": (_SWEEP_CORPORA["cross_tool"], "."),
    "lookup_project": (_SWEEP_CORPORA["lookup_project"], "."),
    "xns_repo": (_SWEEP_CORPORA["xns_repo"].parent, "app"),
    "multirepo_namespace": (_SWEEP_CORPORA["multirepo_namespace"].parent, "app"),
    "src_layout": (Path(__file__).parent / "fixtures" / "added_sys_path_project", "."),
}

#: Seeds per corpus (the first few modules plus the configured extras); enough
#: to reach every response shape without sweeping whole trees.
_SEEDS_PER_CORPUS = 6


def _path_problems(value: Any, where: str) -> list[str]:
    if not isinstance(value, str):
        return [f"{where}: not a string: {value!r}"]
    problems = []
    if "\\" in value:
        problems.append(f"{where}: backslash in {value!r}")
    if not (value.startswith("/") or _DRIVE.match(value)):
        problems.append(f"{where}: not absolute: {value!r}")
    if ".." in value.split("/"):
        problems.append(f"{where}: '..' segment in {value!r}")
    return problems


def walk(obj: Any, where: str = "$") -> list[str]:
    """Every boundary-contract problem among the path values in *obj*."""
    problems: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f"{where}.{key}"
            if key in _PATH_KEYS and value is not None:
                problems += _path_problems(value, here)
            elif key in _PATH_LIST_KEYS and isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, str):
                        problems += _path_problems(item, f"{here}[{i}]")
                    else:
                        problems += walk(item, f"{here}[{i}]")
            elif key == "namespaces" and isinstance(value, dict):
                for ns, paths in value.items():
                    for i, item in enumerate(paths or []):
                        problems += _path_problems(item, f"{here}.{ns}[{i}]")
            else:
                problems += walk(value, here)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            problems += walk(item, f"{where}[{i}]")
    return problems


# ---------------------------------------------------------------------------
# The walker itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ("/abs/pkg/mod.py", True),
        ("C:/Users/x/pkg/mod.py", True),
        ("pkg/mod.py", False),
        ("C:\\Users\\x\\mod.py", False),
        ("/abs/pkg/../mod.py", False),
    ],
)
def test_walker_flags_bad_paths(value: str, ok: bool) -> None:
    problems = walk({"location": {"file": value}, "packages": [value]})
    assert (not problems) is ok, problems


def test_walker_ignores_non_path_keys() -> None:
    assert (
        walk({"report_issues": "https://x/issues", "detail": "see a/../b", "handle": "a.b"}) == []
    )


# ---------------------------------------------------------------------------
# Core tools
# ---------------------------------------------------------------------------


@pytest.fixture(params=sorted(_CORPORA))
def corpus_root(request, tmp_path: Path) -> tuple[str, Path]:
    source, rel = _CORPORA[request.param]
    copy = tmp_path / source.name
    shutil.copytree(source, copy)
    return request.param, (copy / rel)


@pytest.mark.asyncio
async def test_core_tool_responses_obey_the_path_contract(corpus_root: tuple[str, Path]) -> None:
    corpus, root = corpus_root
    project = root.as_posix()
    seeds = _module_seeds(root)[:_SEEDS_PER_CORPUS] + _EXTRA_SEEDS.get(corpus, [])
    responses: list[tuple[str, Any]] = [
        ("configure_packages", await server.configure_packages(project_path=project))
    ]
    for seed in seeds:
        responses.append((f"resolve({seed})", await server.resolve(seed, project_path=project)))
        node = await server.inspect(seed, project_path=project)
        responses.append((f"inspect({seed})", node))
        responses.append((f"outline({seed})", await server.outline(seed, project_path=project)))
        for edge in EDGE_RESOLVERS:
            responses.append(
                (f"expand({seed}, {edge})", await server.expand(seed, edge, project_path=project))
            )
        responses.append(
            (f"trace({seed})", await server.trace(seed, list(EDGE_RESOLVERS), project_path=project))
        )
        location = node.get("location") or {}
        if location.get("file"):
            responses.append(
                (
                    f"resolve_at({seed})",
                    await server.resolve_at(
                        location["file"],
                        location.get("line_start", 1),
                        location.get("column_start", 0),
                        project_path=project,
                    ),
                )
            )
    assert any(walk_has_paths(r) for _, r in responses), f"{corpus}: no path was returned at all"
    problems = [f"{name}: {p}" for name, r in responses for p in walk(r)]
    assert not problems, "\n".join(problems[:40])


def walk_has_paths(obj: Any) -> bool:
    """Whether *obj* carries at least one path value (guards a vacuous pass)."""
    if isinstance(obj, dict):
        return any(
            (k in _PATH_KEYS and v) or (k in _PATH_LIST_KEYS and v) or walk_has_paths(v)
            for k, v in obj.items()
        )
    if isinstance(obj, list):
        return any(walk_has_paths(v) for v in obj)
    return False


# ---------------------------------------------------------------------------
# Plugin tools (pydantic, django, flask), envelope and bare
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("envelope", [True, False])
async def test_plugin_tool_responses_obey_the_path_contract(tmp_path: Path, envelope: bool) -> None:
    main = tmp_path / "main"
    (main / "app").mkdir(parents=True)
    (main / "app" / "models.py").write_text(
        "from pydantic import BaseModel\n\n\nclass MainModel(BaseModel):\n    x: int\n"
    )
    shared = tmp_path / "shared"
    (shared / "lib").mkdir(parents=True)
    (shared / "lib" / "models.py").write_text(
        "from pydantic import BaseModel\n\n\nclass SharedModel(BaseModel):\n    x: int\n"
    )
    config = _config(main, shared, None)
    srv = _wrapped_server(_plugins(main, config), config)

    problems: list[str] = []
    for tool in ALL_TOOLS:
        args = {**EXTRA_ARGS.get(tool, {}), "envelope": envelope}
        result = await srv.call_tool(tool, args)
        assert not result.is_error, (tool, result.content)
        payloads = [json.loads(c.text) for c in result.content if getattr(c, "text", None)]
        problems += [f"{tool}: {p}" for p in walk(payloads)]
    assert not problems, "\n".join(problems[:40])
