"""The one truncation-reason table agrees with the linter, the tools and the docs (#435).

``completeness.TRUNCATION_REASONS`` is the single list of reasons. The response
linter keeps its own hardcoded copies on purpose (an independent oracle), so
these tests pin the copies to the table. They also check that the tool
descriptions an agent reads and the ``python-explore`` skill name every reason
the tool can emit, so a new reason can't ship undocumented.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from pyeye.mcp.operations import completeness
from pyeye.mcp.operations.completeness import (
    BOUNDARY,
    BUDGET,
    TRUNCATION_REASONS,
    UNMEASURED,
    reasons_emitted_by,
    reasons_of_class,
)
from tests.conformance import response_linter

server = importlib.import_module("pyeye.mcp.server")
_SKILL = Path(__file__).parent.parent / "skills" / "python-explore" / "SKILL.md"


def test_every_reason_is_well_formed() -> None:
    for name, reason in TRUNCATION_REASONS.items():
        assert reason.name == name
        assert reason.cls in {BUDGET, BOUNDARY, UNMEASURED}, name
        assert reason.recovery.strip(), name
        assert reason.emitted_by <= {"outline", "trace", "expand", "resolve"}, name
        assert reason.emitted_by, name


def test_linter_outline_set_is_the_table() -> None:
    assert reasons_emitted_by("outline") == response_linter._VALID_OUTLINE_TRUNCATION_REASONS


def test_linter_trace_set_is_the_table() -> None:
    assert reasons_emitted_by("trace") == response_linter._VALID_TRUNCATION_REASONS


def test_linter_budget_set_is_the_table() -> None:
    """The linter's per-node budget set is outline's budget reasons."""
    assert reasons_of_class(BUDGET) & reasons_emitted_by("outline") == (
        response_linter._BUDGET_REASONS
    )


def test_linter_list_cap_reasons_are_the_table() -> None:
    """The flat-list caps (#435 slice B): one budget reason per tool."""
    assert {
        tool: frozenset({reason}) for tool, (_key, reason) in response_linter._LIST_CAPS.items()
    } == {tool: reasons_emitted_by(tool) for tool in ("expand", "resolve")}
    for reason in ("max_stubs", "max_candidates"):
        assert TRUNCATION_REASONS[reason].cls == BUDGET


def test_code_constants_are_the_table_names() -> None:
    for const in (
        "MAX_DEPTH",
        "MAX_NODES",
        "EXTERNAL",
        "SURVEY_LEAF",
        "UNPARSEABLE",
        "MAX_STUBS",
        "MAX_CANDIDATES",
    ):
        assert getattr(completeness, const) in TRUNCATION_REASONS


@pytest.mark.parametrize("tool", ["outline", "trace", "expand", "resolve"])
def test_tool_description_names_every_reason(tool: str) -> None:
    description = server.mcp._tool_manager._tools[tool].description or ""
    missing = [r for r in sorted(reasons_emitted_by(tool)) if f'"{r}"' not in description]
    assert not missing, f"{tool}'s description omits truncation reasons {missing}"


def test_skill_names_every_outline_reason() -> None:
    skill = _SKILL.read_text(encoding="utf-8")
    missing = [r for r in sorted(reasons_emitted_by("outline")) if r not in skill]
    assert not missing, f"python-explore SKILL.md omits truncation reasons {missing}"
