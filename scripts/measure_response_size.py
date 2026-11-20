#!/usr/bin/env python3
"""What a per-node response key costs in bytes, on real responses (#933).

Calls pyeye's tools through the MCP server (so the bytes are the wire form's
text content), on the dogfooding scenarios plus a plugin fixture, and compares
each response's size with and without one key on every node: every dict that
carries both ``handle`` and ``scope``, the nodes ``scope`` already marks.

Two modes, so the same command measures before and after a change:

* ``--mode inject`` (a build that doesn't emit the key yet): the key is
  inserted after ``scope`` with the value a ``.pyi`` file would give
  (``stub``), else ``source``. This is a pre-build estimate.
* ``--mode strip`` (a build that emits it): the key is removed to get the
  "before" size. This measures the real cost on the built output.

Each response is re-serialised exactly as the server wrote its text content
(detected per response: ``indent=2``, the json default, or compact), so the
percentages are of the bytes an agent receives.

It measures; it doesn't judge. The summary gives the median per-response
increase over all responses and over those that contain any node, the total,
and per type (each tool, and each ``expand`` edge) the aggregate, median and
largest increase. The threshold is the caller's (the PR's record).

The build under test is whatever ``pyeye`` this interpreter imports; run it
from the checkout being measured. It is a heavy job: run it memory-capped.

Usage:
    measure_response_size.py OUT.json [--mode inject|strip] [--key declared_in]
                             [--scenarios DIR]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import platform
import shutil
import statistics
import subprocess  # nosec B404 - runs git rev-parse only, for the record
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

#: The probe set: per scenario, the modules outlined, the handles resolved,
#: inspected and expanded along every edge, and the traces (start, follow, depth;
#: ``None`` follows every implemented edge). Changing it changes the record.
CORPORA: dict[str, dict[str, Any]] = {
    "django": {
        "project": "django",
        "outline": [
            "django.db.models.base",
            "django.db.models.query",
            "django.http.request",
            "django.urls.resolvers",
            "django.forms.forms",
            "django.contrib.auth.models",
            "django.core.handlers.base",
            "django.template.base",
        ],
        "expand": [
            "django.db.models",
            "django.db.models.base.Model",
            "django.db.models.query.QuerySet",
            "django.http.request.HttpRequest",
            "django.contrib.auth.models.User",
            "django.forms.forms.Form",
        ],
        "trace": [
            ("django.db.models.base.Model", None, 2),
            ("django.http.request", ["imports"], 2),
        ],
    },
    "jaraco": {
        "project": "jaraco.text",
        "outline": ["jaraco.text", "jaraco.functools", "jaraco.context"],
        "expand": [
            "jaraco.text",
            "jaraco.text.FoldedCase",
            "jaraco.functools.compose",
            "jaraco.context.ExceptionTrap",
        ],
        "trace": [
            ("jaraco.text", ["imports"], 3),
            ("jaraco.text.FoldedCase", None, 2),
        ],
    },
}

#: The plugin listings run on this fixture (pydantic + flask), given an
#: environment as the docs examples are. Tools that need a model name are skipped.
PLUGIN_FIXTURE = ROOT / "tests" / "fixtures" / "docs_examples"
PLUGIN_TOOLS_SKIPPED = frozenset({"get_model_schema", "trace_model_inheritance"})

_SERIALISERS: dict[str, dict[str, Any]] = {
    "indent2": {"indent": 2},
    "default": {},
    "compact": {"separators": (",", ":")},
}


@dataclass(frozen=True)
class Marker:
    """The key measured, and how the before/after pair is made."""

    key: str
    mode: str  # "inject" or "strip"


def _file_of(node: dict[str, Any]) -> str | None:
    location = node.get("location")
    if isinstance(location, dict) and isinstance(location.get("file"), str):
        return str(location["file"])
    file = node.get("file")
    return file if isinstance(file, str) else None


def is_node(obj: Any) -> bool:
    """Whether *obj* is a node: a dict that carries both ``handle`` and ``scope``."""
    return isinstance(obj, dict) and "handle" in obj and "scope" in obj


def transform(obj: Any, marker: Marker) -> tuple[Any, int]:
    """*obj* with *marker*'s key inserted after ``scope`` (inject) or removed (strip).

    Returns the copy and the number of nodes seen. Only nodes change; key order
    is kept, so the bytes differ by the key alone.
    """
    nodes = 0

    def walk(value: Any) -> Any:
        nonlocal nodes
        if isinstance(value, list):
            return [walk(v) for v in value]
        if not isinstance(value, dict):
            return value
        node = is_node(value)
        nodes += node
        out: dict[str, Any] = {}
        for key, item in value.items():
            if marker.mode == "strip" and node and key == marker.key:
                continue
            out[key] = walk(item)
            if marker.mode == "inject" and node and key == "scope" and marker.key not in value:
                file = _file_of(value)
                out[marker.key] = "stub" if file and file.lower().endswith(".pyi") else "source"
        return out

    return walk(obj), nodes


def serialiser_for(text: str, structured: Any) -> str:
    """Which serialiser wrote *text* from *structured*; ``indent2`` when none matches."""
    for name, kwargs in _SERIALISERS.items():
        if json.dumps(structured, ensure_ascii=False, **kwargs) == text:
            return name
    return "indent2"


def size(obj: Any, serialiser: str) -> int:
    """UTF-8 bytes of *obj* as *serialiser* writes it."""
    return len(json.dumps(obj, ensure_ascii=False, **_SERIALISERS[serialiser]).encode())


def measure_result(result: Any, marker: Marker) -> dict[str, Any]:
    """One response's before/after bytes, from an MCP ``CallToolResult``."""
    texts = [c.text for c in result.content if getattr(c, "text", None)]
    structured = result.structured_content
    if structured is None and texts:
        structured = json.loads(texts[0])
    serialiser = serialiser_for(texts[0], structured) if texts else "indent2"
    changed, nodes = transform(structured, marker)
    as_built, other = size(structured, serialiser), size(changed, serialiser)
    before, after = (other, as_built) if marker.mode == "strip" else (as_built, other)
    return {
        "is_error": bool(result.is_error),
        "serialiser": serialiser,
        "nodes": nodes,
        "before": before,
        "after": after,
    }


def _pct(before: int, after: int) -> float:
    return 100.0 * (after - before) / before if before else 0.0


def response_type(row: dict[str, Any]) -> list[str]:
    """The types a row counts toward: its tool, and for ``expand`` its edge too."""
    if row["tool"] == "expand":
        return ["expand", f"expand:{row['args']['edge']}"]
    return [row["tool"]]


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Medians, total and per-type growth over the rows that didn't error."""
    ok = [r for r in rows if not r["is_error"]]
    with_nodes = [r for r in ok if r["nodes"]]
    by_type: dict[str, list[dict[str, Any]]] = {}
    for row in ok:
        for key in response_type(row):
            by_type.setdefault(key, []).append(row)

    def median(of: list[dict[str, Any]]) -> float:
        return round(statistics.median(_pct(r["before"], r["after"]) for r in of), 2) if of else 0.0

    types = {
        key: {
            "responses": len(group),
            "bytes_before": sum(r["before"] for r in group),
            "bytes_after": sum(r["after"] for r in group),
            "aggregate_pct": round(
                _pct(sum(r["before"] for r in group), sum(r["after"] for r in group)), 2
            ),
            "median_pct": median(group),
            "max_single_pct": round(max(_pct(r["before"], r["after"]) for r in group), 2),
        }
        for key, group in sorted(by_type.items())
    }
    return {
        "responses": len(rows),
        "errors": len(rows) - len(ok),
        "serialisers": sorted({r["serialiser"] for r in ok}),
        "median_pct_all": median(ok),
        "median_pct_with_nodes": median(with_nodes),
        "total_pct": round(_pct(sum(r["before"] for r in ok), sum(r["after"] for r in ok)), 2),
        "types": types,
    }


async def _core_rows(scenarios: Path, marker: Marker) -> list[dict[str, Any]]:
    from pyeye.mcp.operations.edges import EDGE_RESOLVERS
    from pyeye.mcp.server import mcp

    rows: list[dict[str, Any]] = []

    async def call(corpus: str, tool: str, args: dict[str, Any], project: str) -> None:
        result = await mcp.call_tool(tool, {**args, "project_path": project})
        rows.append(
            {"corpus": corpus, "tool": tool, "args": args, **measure_result(result, marker)}
        )

    for corpus, spec in CORPORA.items():
        project = (scenarios / spec["project"]).as_posix()
        for handle in spec["outline"]:
            await call(corpus, "outline", {"handle": handle}, project)
        for handle in spec["expand"]:
            await call(corpus, "resolve", {"identifier": handle}, project)
            await call(corpus, "inspect", {"handle": handle}, project)
            for edge in sorted(EDGE_RESOLVERS):
                await call(corpus, "expand", {"handle": handle, "edge": edge}, project)
        for start, follow, depth in spec["trace"]:
            args = {"start": start, "follow": follow or sorted(EDGE_RESOLVERS), "max_depth": depth}
            await call(corpus, "trace", args, project)
    return rows


async def _plugin_rows(marker: Marker) -> list[dict[str, Any]]:
    from mcp.server.mcpserver import MCPServer

    from pyeye.config import ProjectConfig
    from pyeye.mcp import server as srv
    from pyeye.scope_utils import SmartScopeResolver

    sys.path.insert(0, ROOT.as_posix())
    from tests.utils.environment import give_installed_packages

    rows: list[dict[str, Any]] = []
    tmp = Path(tempfile.mkdtemp(prefix="measure-plugins-"))
    try:
        project = tmp / "project"
        shutil.copytree(PLUGIN_FIXTURE, project)
        give_installed_packages(project)
        server = MCPServer("measure-plugins")
        config = ProjectConfig(project.as_posix())
        plugins = [cls(project.as_posix()) for cls in srv._PLUGIN_CLASSES]
        for plugin in plugins:
            srv._apply_plugin_paths(plugin, config)
        srv.register_plugin_tools(server, plugins, SmartScopeResolver(config))
        for tool in sorted(t.name for t in await server.list_tools()):
            if tool in PLUGIN_TOOLS_SKIPPED:
                continue
            result = await server.call_tool(tool, {"project_path": project.as_posix()})
            rows.append(
                {"corpus": "plugins", "tool": tool, "args": {}, **measure_result(result, marker)}
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return rows


def _record(args: argparse.Namespace) -> dict[str, Any]:
    """The D12 record's reproducibility fields: when, which build, where, on what."""

    def rev(path: Path) -> str | None:
        try:
            out = subprocess.run(  # nosec B603 B607 - fixed git argv, no shell
                ["git", "-C", path.as_posix(), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        return out.stdout.strip()

    scenarios = Path(args.scenarios)
    return {
        "date": date.today().isoformat(),
        "commit": rev(ROOT),
        "scenarios": {c["project"]: rev(scenarios / c["project"]) for c in CORPORA.values()},
        "machine": f"{platform.system()} {platform.release()}, Python {platform.python_version()}",
        "command": " ".join(["measure_response_size.py", *sys.argv[1:]]),
        "key": args.key,
        "mode": args.mode,
    }


def main(argv: list[str] | None = None) -> int:
    """Measure, write *out* (record, summary and rows) and print the record and summary."""
    parser = argparse.ArgumentParser(
        description="What a per-node response key costs in bytes (#933)."
    )
    parser.add_argument("out", type=Path, help="where to write the rows and summary (JSON)")
    parser.add_argument("--mode", choices=("inject", "strip"), default="inject")
    parser.add_argument("--key", default="declared_in")
    parser.add_argument("--scenarios", default=(ROOT / ".scenario-repos").as_posix())
    args = parser.parse_args(argv)
    logging.disable(logging.CRITICAL)

    marker = Marker(args.key, args.mode)
    scenarios = Path(args.scenarios)

    async def run() -> list[dict[str, Any]]:
        return [*await _core_rows(scenarios, marker), *await _plugin_rows(marker)]

    rows = asyncio.run(run())
    data = {"record": _record(args), "summary": summarise(rows), "rows": rows}
    args.out.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(json.dumps({"record": data["record"], "summary": data["summary"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
