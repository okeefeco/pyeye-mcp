"""The response-size measurement behind #933's record (``scripts/measure_response_size.py``).

The script's real run needs the dogfooding scenarios, so it isn't run here.
What is tested is everything its numbers depend on: which dicts count as
nodes, the inject/strip transform, matching the server's serialiser, the
before/after pairing in each mode, and the summary's medians and types.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "measure_response_size.py"
_spec = importlib.util.spec_from_file_location("measure_response_size", _SCRIPT)
assert _spec is not None and _spec.loader is not None
mrs = importlib.util.module_from_spec(_spec)
sys.modules["measure_response_size"] = mrs
_spec.loader.exec_module(mrs)

INJECT = mrs.Marker("declared_in", "inject")
STRIP = mrs.Marker("declared_in", "strip")

RESPONSE: dict[str, Any] = {
    "found": True,
    "source": "pkg",
    "edge": "members",
    "stubs": [
        {"handle": "pkg.a", "kind": "function", "scope": "project", "line_start": 1},
        {
            "handle": "pkg.S",
            "kind": "class",
            "scope": "project",
            "location": {"file": "/p/pkg/stubonly.pyi", "line_start": 3},
        },
    ],
    "ceiling": "static_definitions",
    "scope": "not a node: no handle",
}


def _result(structured: Any, **dumps: Any) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(text=json.dumps(structured, ensure_ascii=False, **dumps))],
        structured_content=structured,
        is_error=False,
    )


class TestTransform:
    def test_inject_adds_the_key_after_scope_on_nodes_only(self) -> None:
        changed, nodes = mrs.transform(RESPONSE, INJECT)

        assert nodes == 2
        assert list(changed["stubs"][0]) == ["handle", "kind", "scope", "declared_in", "line_start"]
        assert changed["stubs"][0]["declared_in"] == "source"
        assert changed["stubs"][1]["declared_in"] == "stub"  # its location is a .pyi
        assert "declared_in" not in changed  # the top level has no handle
        assert RESPONSE["stubs"][0].get("declared_in") is None  # the input is untouched

    def test_strip_is_injects_inverse(self) -> None:
        injected, _ = mrs.transform(RESPONSE, INJECT)
        stripped, nodes = mrs.transform(injected, STRIP)

        assert nodes == 2 and stripped == RESPONSE

    def test_inject_leaves_a_key_already_there(self) -> None:
        node = {"handle": "h", "scope": "project", "declared_in": "stub"}

        assert mrs.transform(node, INJECT)[0] == node

    def test_nested_nodes_count(self) -> None:
        tree = {
            "node": {"handle": "m", "scope": "project"},
            "children": [{"node": {"handle": "m.f", "scope": "project"}}],
        }

        assert mrs.transform(tree, INJECT)[1] == 2


class TestSerialiser:
    @pytest.mark.parametrize(
        ("name", "dumps"),
        [("indent2", {"indent": 2}), ("default", {}), ("compact", {"separators": (",", ":")})],
    )
    def test_the_servers_form_is_detected(self, name: str, dumps: dict[str, Any]) -> None:
        text = json.dumps(RESPONSE, ensure_ascii=False, **dumps)

        assert mrs.serialiser_for(text, RESPONSE) == name

    def test_bytes_are_utf8(self) -> None:
        assert mrs.size({"k": "é"}, "compact") == len('{"k":"é"}'.encode())


class TestMeasureResult:
    def test_inject_measures_the_key_added(self) -> None:
        row = mrs.measure_result(_result(RESPONSE, indent=2), INJECT)
        injected, _ = mrs.transform(RESPONSE, INJECT)

        assert row["serialiser"] == "indent2" and row["nodes"] == 2
        assert row["before"] == mrs.size(RESPONSE, "indent2")
        assert row["after"] == mrs.size(injected, "indent2")

    def test_strip_measures_the_key_already_built(self) -> None:
        built, _ = mrs.transform(RESPONSE, INJECT)
        row = mrs.measure_result(_result(built, indent=2), STRIP)

        assert (row["before"], row["after"]) == (
            mrs.size(RESPONSE, "indent2"),
            mrs.size(built, "indent2"),
        )

    def test_both_modes_agree_on_the_same_change(self) -> None:
        """The pre-build estimate and the post-build measurement give one number."""
        built, _ = mrs.transform(RESPONSE, INJECT)
        estimate = mrs.measure_result(_result(RESPONSE, indent=2), INJECT)
        measured = mrs.measure_result(_result(built, indent=2), STRIP)

        assert (estimate["before"], estimate["after"]) == (measured["before"], measured["after"])


def _row(
    tool: str, before: int, after: int, nodes: int = 1, edge: str | None = None
) -> dict[str, Any]:
    args = {"edge": edge} if edge else {}
    return {
        "tool": tool,
        "args": args,
        "is_error": False,
        "serialiser": "indent2",
        "nodes": nodes,
        "before": before,
        "after": after,
    }


class TestSummarise:
    def test_medians_totals_and_types(self) -> None:
        rows = [
            _row("expand", 100, 110, edge="members"),
            _row("expand", 100, 100, nodes=0, edge="callees"),
            _row("outline", 200, 220),
            {**_row("inspect", 50, 60), "is_error": True},
        ]

        summary = mrs.summarise(rows)

        assert (summary["responses"], summary["errors"]) == (4, 1)
        assert summary["median_pct_all"] == 10.0  # 10, 0, 10
        assert summary["median_pct_with_nodes"] == 10.0  # the empty callees row is excluded
        assert summary["total_pct"] == 7.5  # 400 -> 430
        assert set(summary["types"]) == {"expand", "expand:members", "expand:callees", "outline"}
        assert summary["types"]["expand"]["aggregate_pct"] == 5.0
        assert summary["types"]["expand"]["max_single_pct"] == 10.0

    def test_no_rows_is_not_an_error(self) -> None:
        assert mrs.summarise([])["median_pct_all"] == 0.0
