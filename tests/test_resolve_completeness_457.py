"""resolve()-level regression for #457 (synthetic, CI-portable).

The issue's user-facing symptom is a false-confident *single* ``resolve()`` hit
for a high-frequency name whose definitions exceed Jedi's 30-parsed-file search
cap. This reproduces it with N>30 synthetic modules defining the same class —
no third-party scenario, so it runs in CI. (Task 3 covers the lower
``_search_all_scopes`` layer; the real django scenario is exercised manually via
the ``pyeye-verify`` skill, not here — ``.scenario-repos`` is never provisioned
in CI.)

On ``main`` (``jedi.Project.search``) ``resolve("Field")`` truncates at 30 parsed
files and returns a false-confident single/partial hit; on this branch the AST
name-index returns every definition, so ``resolve`` is honestly ambiguous.
"""

from pathlib import Path

import pytest

from pyeye.analyzers import project_graph
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.resolve import resolve

# Comfortably above Jedi's 30-parsed-file cap so truncation would drop candidates.
_N = 40

# The ``class Field`` deliberately does NOT sit on line 1 / column 0, so a real
# def-site location is distinguishable from the degraded line-1/col-0 fallback
# (#457). The resolved location points at the name token ``Field`` (column
# ``len("class ")``), Jedi's convention — not at the ``class`` keyword.
_FIELD_LINE = 5
_FIELD_COLUMN = len("class ")
_FIELD_SOURCE = '"""Module docstring."""\n' + "\n" * (_FIELD_LINE - 2) + "class Field:\n    pass\n"


@pytest.fixture
def many_field_modules(tmp_path: Path) -> Path:
    """A project with the same class ``Field`` (on line ``_FIELD_LINE``) in N>30 modules."""
    for i in range(_N):
        (tmp_path / f"m{i:02d}.py").write_text(_FIELD_SOURCE)
    project_graph.invalidate()
    return tmp_path


@pytest.mark.asyncio
async def test_resolve_high_frequency_name_is_ambiguous_not_truncated(
    many_field_modules: Path,
) -> None:
    analyzer = JediAnalyzer(str(many_field_modules))

    result = await resolve("Field", analyzer)

    assert result.get("found") is True
    assert result.get("ambiguous") is True, f"expected ambiguous, got {result}"
    handles = {c["handle"] for c in result.get("candidates", [])}
    # Every definition is present — not truncated to the 30-parsed-file cap.
    assert handles == {f"m{i:02d}.Field" for i in range(_N)}


@pytest.mark.asyncio
async def test_resolve_dotted_high_frequency_name_has_real_line(
    many_field_modules: Path,
) -> None:
    analyzer = JediAnalyzer(str(many_field_modules))

    result = await resolve("m39.Field", analyzer)

    assert result.get("found") is True
    assert result.get("handle") == "m39.Field"
    # The class sits on line _FIELD_LINE (>1), so this asserts the REAL def-site
    # line: if the degraded line-1/col-0 fallback fired (the #457 symptom), this
    # would see line 1 and fail. A line-1 fixture could not tell the two apart.
    location = result.get("location") or {}
    assert location.get("line_start") == _FIELD_LINE, location
    assert location.get("column_start") == _FIELD_COLUMN, location
