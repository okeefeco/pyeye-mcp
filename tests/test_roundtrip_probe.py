"""Tests for the pyeye-verify round-trip probe script (#616).

The probe feeds every stub from one ``expand(<module>, "imports")`` back into
``inspect`` and ``resolve`` and counts the handles that don't round-trip. Its
job is to *measure*, so these tests pin the bucket arithmetic (with stubbed
primitives) and check one real run end to end. They deliberately don't assert
today's known external misses: those belong to #614's allow-listed
``test_emitted_handles_round_trip`` and close under #623.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "roundtrip_probe.py"
_spec = importlib.util.spec_from_file_location("roundtrip_probe", _SCRIPT)
assert _spec and _spec.loader
rt = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rt  # dataclasses resolve their module via sys.modules
_spec.loader.exec_module(rt)


def _op(name: str) -> ModuleType:
    """The operation *module*; ``pyeye.mcp.operations.<name>`` as a dotted
    string resolves to the re-exported function, not the module."""
    return importlib.import_module(f"pyeye.mcp.operations.{name}")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "b.py").write_text("def thing():\n    return 1\n", encoding="utf-8")
    (pkg / "a.py").write_text(
        "import os\nfrom pkg.b import thing\n\n\ndef use():\n    return thing(), os.sep\n",
        encoding="utf-8",
    )
    return tmp_path


def _patch_primitives(
    monkeypatch: pytest.MonkeyPatch,
    stubs: list[dict[str, Any]],
    inspect_results: dict[str, dict[str, Any]],
    resolve_results: dict[str, dict[str, Any]],
) -> None:
    async def fake_expand(_handle: str, edge: str, _analyzer: Any) -> dict[str, Any]:
        assert edge == "imports"
        return {"found": True, "stubs": stubs}

    async def fake_inspect(handle: str, _analyzer: Any) -> dict[str, Any]:
        return inspect_results[handle]

    async def fake_resolve(handle: str, _analyzer: Any) -> dict[str, Any]:
        return resolve_results[handle]

    monkeypatch.setattr(_op("expand"), "expand", fake_expand)
    monkeypatch.setattr(_op("inspect"), "inspect", fake_inspect)
    monkeypatch.setattr(_op("resolve"), "resolve", fake_resolve)


async def test_buckets_each_failure_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    stubs = [
        {"handle": "ok", "scope": "project"},
        {"handle": "ok", "scope": "project"},  # duplicate stub counted once
        {"handle": "both_miss", "scope": "external"},
        {"handle": "inspect_only", "scope": "external"},
        {"handle": "renamed", "scope": "project"},
    ]
    inspect_results = {
        "ok": {"handle": "ok"},  # inspect omits ``found`` on success
        "both_miss": {"found": False},
        "inspect_only": {"handle": "inspect_only"},
        "renamed": {"handle": "pkg.real"},
    }
    resolve_results = {
        "ok": {"found": True, "handle": "ok"},
        "both_miss": {"found": False},
        "inspect_only": {"found": False},
        "renamed": {"found": True, "handle": "pkg.other"},
    }
    _patch_primitives(monkeypatch, stubs, inspect_results, resolve_results)

    result = await rt.probe("/unused", "pkg.a", analyzer=object())

    assert result.stubs == 4
    assert result.inspect_miss == ["both_miss"]
    assert result.resolve_miss == ["both_miss", "inspect_only"]
    assert result.disagree == ["inspect_only"]
    assert result.handle_mismatch == ["renamed"]
    assert result.not_round_tripping == 3
    assert result.miss_scopes == {"external": 2}


async def test_clean_module_reports_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_primitives(
        monkeypatch,
        [{"handle": "x", "scope": "project"}],
        {"x": {"handle": "x"}},
        {"x": {"found": True, "handle": "x"}},
    )
    result = await rt.probe("/unused", "m", analyzer=object())
    assert (result.stubs, result.not_round_tripping) == (1, 0)
    assert "1 stub(s); 0 don't round-trip" in rt.format_summary(result)


async def test_expand_not_found_is_an_error_not_a_clean_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_expand(_handle: str, _edge: str, _analyzer: Any) -> dict[str, Any]:
        return {"found": False}

    monkeypatch.setattr(_op("expand"), "expand", fake_expand)
    with pytest.raises(RuntimeError, match="not found"):
        await rt.probe("/unused", "nope", analyzer=object())


def test_summary_lists_examples_and_scopes() -> None:
    result = rt.RoundTripResult(project_path="p", module="m", stubs=7)
    result.inspect_miss = [f"h{i}" for i in range(7)]
    result.resolve_miss = list(result.inspect_miss)
    result.miss_scopes = {"external": 7}
    text = rt.format_summary(result)
    assert "7 don't round-trip" in text
    assert "misses by stub scope: external=7" in text
    assert "h4 …" in text and "h5" not in text


async def test_real_project_stub_round_trips(project: Path) -> None:
    """End to end: the project import is emitted and resolves through both tools."""
    result = await rt.probe(str(project), "pkg.a", analyzer=JediAnalyzer(str(project)))
    assert result.stubs >= 2
    for bucket in (result.inspect_miss, result.resolve_miss, result.handle_mismatch):
        assert "pkg.b.thing" not in bucket


def test_cli_json_and_text(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_primitives(
        monkeypatch,
        [{"handle": "x", "scope": "external"}],
        {"x": {"found": False}},
        {"x": {"found": False}},
    )
    monkeypatch.setattr(
        "pyeye.project_manager.ProjectManager.get_analyzer", lambda _self, _path: object()
    )

    assert rt.main([str(project), "pkg.a", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["not_round_tripping"] == 1
    assert payload["inspect_miss"] == ["x"]

    assert rt.main([str(project), "pkg.a"]) == 0
    assert "1 don't round-trip" in capsys.readouterr().out


def test_cli_expand_not_found_exits_2(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_expand(_handle: str, _edge: str, _analyzer: Any) -> dict[str, Any]:
        return {"found": False}

    monkeypatch.setattr(_op("expand"), "expand", fake_expand)
    monkeypatch.setattr(
        "pyeye.project_manager.ProjectManager.get_analyzer", lambda _self, _path: object()
    )
    assert rt.main([str(project), "nope"]) == 2
    assert "not found" in capsys.readouterr().err
