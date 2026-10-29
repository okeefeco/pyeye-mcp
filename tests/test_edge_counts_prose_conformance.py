"""Conformance: shipped prose must not show an unmeasured edge inside ``edge_counts``.

``test_python_explore_skill_conformance`` checks the skill's supported-edge
*list* against the edge registry, but nothing checked example *prose*. In #392 /
PR #395, ``subclasses`` was correctly dropped from ``inspect``'s ``edge_counts``
while three skill examples and two ``server.py`` docstrings still showed it
there. CI stayed green and a reviewer caught it (#396).

"Unmeasured" comes from ``_PHASE4_UNMEASURED_EDGES`` in the response linter, the
same set that rejects those keys in live ``inspect`` responses, so a change to
the measured set moves both checks together.

The scan is structural, not free-text: within a paragraph that mentions
``edge_counts``, an edge counts as *claimed present* only when it appears as a
brace key (``edge_counts: { …, subclasses: 0 }``), as dotted or subscript access
(``edge_counts.subclasses``), or as a count (``subclasses: 0``). Prose that names
an edge to say it is omitted ("``edge_counts`` omits ``callers``") is correct and
does not match. Claims phrased entirely in free prose ("0 subclasses") are out
of reach and remain review territory.
"""

import re
from pathlib import Path

import pytest

from tests.conformance.response_linter import _PHASE4_UNMEASURED_EDGES

REPO_ROOT = Path(__file__).resolve().parent.parent

# Shipped surfaces that describe inspect's edge_counts to a model or a reader.
# server.py is scanned as source: its tool docstrings are the MCP tool
# descriptions, and the #395 miss was in a comment there too.
SHIPPED_SURFACES = [
    "skills/python-explore/SKILL.md",
    "src/pyeye/mcp/server.py",
    "README.md",
]

_BRACE_FORM = re.compile(r"edge_counts\s*[:=]\s*\{([^}]*)\}")
_BRACE_KEY = re.compile(r"[\"']?(\w+)[\"']?\s*:")
# edge_counts.X, edge_counts["X"], and result["edge_counts"]["X"]
_ACCESS_FORM = re.compile(r"edge_counts(?:[\"']\])?\s*(?:\.\s*(\w+)|\[\s*[\"'](\w+)[\"']\s*\])")
_COUNT_FORM = re.compile(r"\b(\w+)\s*:\s*\d")


def unmeasured_edge_claims(text: str) -> list[str]:
    """Return each place ``text`` presents an unmeasured edge as an edge_counts key."""
    claims: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        if "edge_counts" not in paragraph:
            continue
        # Backticks and line wrapping split RST/markdown spans
        # (``edge_counts``\n``.subclasses``); remove both before matching.
        flat = " ".join(paragraph.replace("`", "").split())

        claimed = [key for body in _BRACE_FORM.findall(flat) for key in _BRACE_KEY.findall(body)]
        claimed += [dotted or subscript for dotted, subscript in _ACCESS_FORM.findall(flat)]
        claimed += _COUNT_FORM.findall(flat)

        # A brace key with a count matches two forms; report each edge once per paragraph.
        for edge in sorted(set(claimed)):
            if edge in _PHASE4_UNMEASURED_EDGES:
                snippet = flat if len(flat) <= 160 else flat[:157] + "..."
                claims.append(f"{edge!r} in: {snippet}")
    return claims


# Verbatim from the pre-#395 tree (parent of c092261): each passed CI while
# contradicting the measured set.
PRE_395_MISSES = {
    "skill example block": (
        'inspect("myapp.config.Settings")   -> kind, signature, docstring,\n'
        "                                        edge_counts: { members: 7, superclasses: 1, "
        "subclasses: 0 }\n"
    ),
    "skill absence-vs-zero paragraph": (
        'When you read `edge_counts`, a **missing key means "not measured," not "zero."** A\n'
        "present `subclasses: 0` means measured-and-none (genuinely unextended). An *absent*\n"
        "`callers` key means pyeye didn't measure it — don't read that as \"no callers.\"\n"
    ),
    "server.py wrapped RST docstring": (
        "        (direct + indirect), so ``len(stubs) == inspect(handle).edge_counts``\n"
        "        ``.subclasses``.  ``stubs: []`` means the class has no project\n"
    ),
    "server.py comment": (
        "# DEPRECATED: replaced by inspect(handle).edge_counts.subclasses for the count; "
        'future expand(handle, edge="subclasses") for the list.\n'
    ),
}

# Correct wording that names unmeasured edges to say they are absent.
CORRECT_OMISSION_PROSE = {
    "omits callers and references": (
        "Likewise, `inspect`'s `edge_counts` simply **omits** `callers`\n"
        "and `references` — it does not report them as `0`.\n"
    ),
    "absent key is not zero": (
        'When you read `edge_counts`, a **missing key means "not measured," not "zero."** A\n'
        "present `superclasses: 0` means measured-and-none (the class has no bases). An *absent*\n"
        "`callers` key means pyeye didn't measure it — don't read that as \"no callers.\"\n"
    ),
    "measured example": "edge_counts: { members: 7, superclasses: 1 }\n",
}


class TestScanner:
    @pytest.mark.parametrize("name", list(PRE_395_MISSES))
    def test_flags_each_pre_395_miss(self, name: str) -> None:
        assert unmeasured_edge_claims(PRE_395_MISSES[name]), name

    @pytest.mark.parametrize("name", list(CORRECT_OMISSION_PROSE))
    def test_does_not_flag_correct_omission_prose(self, name: str) -> None:
        assert unmeasured_edge_claims(CORRECT_OMISSION_PROSE[name]) == []

    @pytest.mark.parametrize(
        "text",
        ['edge_counts["callers"] is the caller count', 'n = result["edge_counts"]["callers"]'],
    )
    def test_flags_subscript_access(self, text: str) -> None:
        assert unmeasured_edge_claims(text)

    def test_measured_set_is_the_linters(self) -> None:
        """subclasses/callers/references are the edges #392 and #332 removed."""
        assert {"subclasses", "callers", "references"} <= _PHASE4_UNMEASURED_EDGES
        assert not {"members", "superclasses"} & _PHASE4_UNMEASURED_EDGES


class TestShippedSurfaces:
    @pytest.mark.parametrize("surface", SHIPPED_SURFACES)
    def test_surface_mentions_edge_counts(self, surface: str) -> None:
        """Fail loudly if a surface stops mentioning edge_counts (scan would be vacuous)."""
        assert "edge_counts" in (REPO_ROOT / surface).read_text(encoding="utf-8")

    @pytest.mark.parametrize("surface", SHIPPED_SURFACES)
    def test_no_unmeasured_edge_shown_in_edge_counts(self, surface: str) -> None:
        claims = unmeasured_edge_claims((REPO_ROOT / surface).read_text(encoding="utf-8"))

        assert not claims, (
            f"{surface} shows edges inside inspect's edge_counts that inspect does not "
            "measure (see _PHASE4_UNMEASURED_EDGES in tests/conformance/response_linter.py). "
            "Either the prose is stale or the measured set changed:\n  " + "\n  ".join(claims)
        )
