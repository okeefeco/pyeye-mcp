"""Production name lookups don't run the re-export scan (#628).

``JediAnalyzer.find_symbol(include_import_paths=True)`` runs the regex
``find_reexports`` scan for every match to fill ``import_paths``. No production
caller reads ``import_paths`` (``inspect`` gets re-exports from
``canonicalization.collect_re_exports``), so with the old default every
``resolve`` paid for the scan and threw the result away. The default is now
``False``; callers that want ``import_paths`` ask for it.
"""

from __future__ import annotations

import inspect as pyinspect
from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.canonicalization import resolve_canonical
from pyeye.mcp.operations.resolve import resolve

_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "resolve_project"


@pytest.fixture
def scans(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []
    original = JediAnalyzer.find_reexports

    def spy(self: JediAnalyzer, *args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(JediAnalyzer, "find_reexports", spy)
    return calls


def test_find_symbol_defaults_to_no_import_paths() -> None:
    default = pyinspect.signature(JediAnalyzer.find_symbol).parameters["include_import_paths"]
    assert default.default is False


@pytest.mark.parametrize(
    "identifier",
    [
        "Widget",  # bare name: resolve._resolve_bare_name
        "mypackage.Widget",  # re-exported dotted path: resolve._resolve_dotted_name
        "mypackage._core.widgets.Widget",  # definition site
    ],
)
async def test_resolve_runs_no_reexport_scan(identifier: str, scans: list[tuple[Any, ...]]) -> None:
    result = await resolve(identifier, JediAnalyzer(str(_FIXTURE)))
    assert result["found"] is True
    assert scans == [], f"resolve({identifier!r}) ran find_reexports {len(scans)} time(s)"


async def test_canonical_resolution_runs_no_reexport_scan(
    scans: list[tuple[Any, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    lookups: list[str] = []
    original = JediAnalyzer.find_symbol

    async def counting(self: JediAnalyzer, name: str, *args: Any, **kwargs: Any) -> Any:
        lookups.append(name)
        return await original(self, name, *args, **kwargs)

    monkeypatch.setattr(JediAnalyzer, "find_symbol", counting)
    # A prefix that is neither a module nor a class falls back to find_symbol.
    await resolve_canonical("mypackage.nosuchmodule.Widget", JediAnalyzer(str(_FIXTURE)))
    assert lookups, "resolve_canonical didn't reach find_symbol; the test is vacuous"
    assert scans == []


async def test_import_paths_still_available_on_request() -> None:
    """The scan still runs when a caller explicitly asks for it."""
    analyzer = JediAnalyzer(str(_FIXTURE))
    results = await analyzer.find_symbol("Widget", include_import_paths=True)
    assert results
    assert all("import_paths" in r for r in results if r.get("type") == "class")
