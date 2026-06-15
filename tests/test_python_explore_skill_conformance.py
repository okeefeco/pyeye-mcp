"""Anti-drift conformance guard for the shipped ``python-explore`` skill.

This test binds the user-facing skill (``skills/python-explore/SKILL.md``) to the
edge registry that is the genuine source of truth
(``pyeye.mcp.operations.edges``).  Issue #374 happened because the skill drifted
from that registry; "the skill is the single source of truth" is an organisational
defence only.  This test converts that drift from a silent rot into a CI failure:
if the implemented edge set changes, the skill's documented anchor must change too,
or this test fails.

Dependency-free by design: stdlib ``re`` + ``pathlib`` only (no yaml).
"""

import re
from pathlib import Path

from pyeye.mcp.operations.edges import (
    _DEFERRED_REFERENCE_BACKEND_EDGES,
    _IMPLEMENTED_EDGES,
)

SKILL = Path(__file__).resolve().parent.parent / "skills" / "python-explore" / "SKILL.md"
_ANCHOR = re.compile(r"<!--\s*pyeye-supported-edges:\s*(.*?)\s*-->")


def _skill_text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _documented_edges() -> set[str]:
    m = _ANCHOR.search(_skill_text())
    assert m is not None, (
        "SKILL.md must embed a `<!-- pyeye-supported-edges: ... -->` anchor "
        "listing the supported expand/trace edges"
    )
    return set(m.group(1).split())


def test_skill_file_exists() -> None:
    assert SKILL.is_file(), f"skill not found at {SKILL.as_posix()}"


def test_documented_edges_equal_implemented_registry() -> None:
    # Drift guard: the skill's supported-edge list must track edges.py exactly.
    assert _documented_edges() == set(_IMPLEMENTED_EDGES)


def test_no_deferred_edge_listed_as_supported() -> None:
    # The #1 bug class: never present a reference-backend edge as available.
    assert _documented_edges().isdisjoint(_DEFERRED_REFERENCE_BACKEND_EDGES)


def test_skill_name_is_stable() -> None:
    # The plugin resolves the skill by this name; a rename would unship it.
    assert re.search(r"^name:\s*python-explore\s*$", _skill_text(), re.MULTILINE)


def test_skill_declares_a_description() -> None:
    assert re.search(r"^description:\s*\S", _skill_text(), re.MULTILINE)


# Pure-legacy tools with NO legitimate reason to appear anywhere in the rewritten
# skill. NOTE: find_references / get_call_hierarchy are deliberately NOT in this set —
# they legitimately appear inside the honest-limits "do NOT use these to fake callers"
# warning, so they cannot be blanket-banned. These four have no such excuse.
_PURE_LEGACY_TOOLS = ("lookup", "find_symbol", "goto_definition", "get_type_info")


def test_pure_legacy_tools_absent() -> None:
    # Mechanical backstop for prose drift: catches a future "use find_symbol" sentence
    # that the edge anchor alone would miss. Manual review remains the backstop for the
    # contextual cases (find_references in the honest-limits warning).
    text = _skill_text()
    present = [t for t in _PURE_LEGACY_TOOLS if t in text]
    assert not present, f"pure-legacy tools must not appear in the skill: {present}"
