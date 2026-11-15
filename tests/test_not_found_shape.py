"""One not-found shape for every primitive (#626 slice A, amending #545).

``{found: false, <lookup echo>, reason, detail}``, with the echo keys and the
closed reason set fixed per operation (``not_found.NOT_FOUND_SPEC``):

* inspect / outline: ``handle``; expand: ``handle``, ``edge``. Reason: ``unresolved``.
* resolve: ``identifier``, never ``handle``.
* resolve_at: flat ``file``, ``line``, ``column``.
* resolve and resolve_at reasons: ``unresolved``, ``file_not_found``,
  ``no_symbol_at_position``.

Before #626, resolve and resolve_at returned a bare ``{found: false, reason}``.
Every miss path is driven here through the real operation, checked against
the exact shape, and run through the response linter's Check N. The server
tool layer is exercised too, so that a spec violation inside the builder
(a ``ValueError``) can't reach a client as a crash.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.not_found import (
    NOT_FOUND_SPEC,
    not_found,
    not_found_for,
)
from pyeye.mcp.operations.resolve import resolve, resolve_at
from tests.conformance.response_linter import lint_response

server = importlib.import_module("pyeye.mcp.server")


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The builder
# ---------------------------------------------------------------------------


class TestBuilder:
    @pytest.mark.parametrize(
        ("operation", "echo"),
        [
            ("inspect", {"handle": "a.b"}),
            ("outline", {"handle": "a.b"}),
            ("expand", {"handle": "a.b", "edge": "members"}),
            ("resolve", {"identifier": "Thing"}),
            ("resolve_at", {"file": "x.py", "line": 3, "column": 0}),
        ],
    )
    def test_shape_and_key_order(self, operation: str, echo: dict[str, Any]) -> None:
        result = not_found_for(operation, echo)
        assert list(result) == ["found", *NOT_FOUND_SPEC[operation].echo_keys, "reason", "detail"]
        assert result["found"] is False
        assert result["reason"] == "unresolved"
        assert result["detail"] and "\n" not in result["detail"]
        lint_response(result, operation)

    @pytest.mark.parametrize("reason", ["unresolved", "file_not_found", "no_symbol_at_position"])
    @pytest.mark.parametrize(
        ("operation", "echo"),
        [
            ("resolve", {"identifier": "src/x.py:3"}),
            ("resolve_at", {"file": "src/x.py", "line": 3, "column": 4}),
        ],
    )
    def test_position_operations_take_all_three_reasons(
        self, operation: str, echo: dict[str, Any], reason: str
    ) -> None:
        result = not_found_for(operation, echo, reason)
        assert result["reason"] == reason
        lint_response(result, operation)

    def test_details_differ_by_reason(self) -> None:
        echo = {"file": "x.py", "line": 3, "column": 0}
        details = {
            reason: not_found_for("resolve_at", echo, reason)["detail"]
            for reason in ("unresolved", "file_not_found", "no_symbol_at_position")
        }
        assert len(set(details.values())) == 3

    def test_explicit_detail_wins(self) -> None:
        result = not_found_for("resolve", {"identifier": "X"}, detail="Try Y.")
        assert result["detail"] == "Try Y."

    def test_resolve_never_echoes_handle(self) -> None:
        with pytest.raises(ValueError, match="echoes"):
            not_found_for("resolve", {"handle": "a.b"})

    def test_unknown_operation(self) -> None:
        with pytest.raises(ValueError, match="no not-found shape"):
            not_found_for("trace", {"handle": "a"})

    def test_reason_outside_the_operations_set(self) -> None:
        with pytest.raises(ValueError, match="reason must be one of"):
            not_found_for("inspect", {"handle": "a"}, "file_not_found")

    def test_missing_or_extra_echo_keys(self) -> None:
        with pytest.raises(ValueError):
            not_found_for("expand", {"handle": "a"})
        with pytest.raises(ValueError):
            not_found_for("resolve_at", {"file": "x.py", "line": 1})

    def test_legacy_not_found_wrapper_is_unchanged(self) -> None:
        assert not_found("pkg.mod.Thing") == {
            "found": False,
            "handle": "pkg.mod.Thing",
            "reason": "unresolved",
            "detail": (
                "Handle 'pkg.mod.Thing' did not resolve to a symbol. "
                "Call resolve('Thing') to find its canonical handle."
            ),
        }
        assert not_found("pkg.Thing", edge="members")["edge"] == "members"


# ---------------------------------------------------------------------------
# resolve / resolve_at miss paths, end to end
# ---------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path: Path) -> Path:
    _write(tmp_path / "pkg" / "__init__.py")
    _write(tmp_path / "pkg" / "mod.py", "\n\nclass Thing:\n    pass\n")
    return tmp_path


def _expect(result: dict[str, Any], operation: str, echo: dict[str, Any], reason: str) -> None:
    assert result["found"] is False
    assert {k: result[k] for k in echo} == echo
    assert "handle" not in result
    assert result["reason"] == reason
    assert set(result) == {"found", *echo, "reason", "detail"}
    lint_response(result, operation)


def _resolve_cases(project: Path) -> list[tuple[str, str]]:
    mod = (project / "pkg" / "mod.py").as_posix()
    missing = (project / "pkg" / "nope.py").as_posix()
    outside = _write(project.parent / f"{project.name}_outside" / "loose.py").as_posix()
    return [
        ("NoSuchSymbolAnywhere", "unresolved"),
        ("pkg.mod.NoSuchThing", "unresolved"),
        (missing, "file_not_found"),
        (f"{missing}:3", "file_not_found"),
        (f"{mod}:1", "no_symbol_at_position"),
        (outside, "unresolved"),
    ]


async def test_every_resolve_miss_path_renders_the_shape(project: Path) -> None:
    analyzer = JediAnalyzer(str(project))
    for identifier, reason in _resolve_cases(project):
        result = dict(await resolve(identifier, analyzer))
        _expect(result, "resolve", {"identifier": identifier}, reason)


async def test_every_resolve_at_miss_path_renders_the_shape(project: Path) -> None:
    analyzer = JediAnalyzer(str(project))
    mod = (project / "pkg" / "mod.py").as_posix()
    missing = (project / "pkg" / "nope.py").as_posix()
    cases = [
        (missing, 1, 0, "file_not_found"),
        (mod, 1, 0, "no_symbol_at_position"),  # blank line
        (mod, 999, 0, "no_symbol_at_position"),  # past the end: Jedi raises
    ]
    for file, line, column, reason in cases:
        result = dict(await resolve_at(file, line, column, analyzer))
        _expect(result, "resolve_at", {"file": file, "line": line, "column": column}, reason)


async def test_resolve_at_echoes_the_callers_spelling(project: Path) -> None:
    """The echo is the input as given, so an agent can match it to its call."""
    analyzer = JediAnalyzer(str(project))
    relative = "pkg/nope.py"
    result = dict(await resolve_at(relative, 2, 5, analyzer))
    assert (result["file"], result["line"], result["column"]) == (relative, 2, 5)


async def test_hits_are_unchanged(project: Path) -> None:
    analyzer = JediAnalyzer(str(project))
    found = await resolve("pkg.mod.Thing", analyzer)
    assert found["found"] is True and found["handle"] == "pkg.mod.Thing"
    at = await resolve_at((project / "pkg" / "mod.py").as_posix(), 3, 6, analyzer)
    assert at["found"] is True and at["handle"] == "pkg.mod.Thing"


async def test_every_miss_through_the_tool_layer_is_a_clean_response(project: Path) -> None:
    """No miss path can turn the builder's ValueError into a client-facing crash."""
    path = project.as_posix()
    for identifier, reason in _resolve_cases(project):
        result = await server.resolve(identifier, project_path=path)
        assert result["found"] is False and result["reason"] == reason
    mod = (project / "pkg" / "mod.py").as_posix()
    result = await server.resolve_at(mod, 1, 0, project_path=path)
    assert result["found"] is False and result["reason"] == "no_symbol_at_position"
