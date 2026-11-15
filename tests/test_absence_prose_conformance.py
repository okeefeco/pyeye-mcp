"""Conformance: shipped prose must not turn "unknown" into "doesn't exist" (#568).

The absence-vs-zero invariant (``docs/api-redesign.md``, "The invariant") is a
general rule: a value pyeye returns is a measured claim over a stated scope, and
anything it doesn't return, or can't resolve, is unknown, not absent.

Two shipped descriptions broke it while CI stayed green:

- the skill's not-found bullet said ``reason: "unresolved"`` means "this handle
  doesn't exist as written", although real symbols (``self.project_path`` set in
  ``__init__``) never resolve;
- the ``members`` / ``outline`` static-surface ceiling said an absent member means
  "not in source", although ``members`` measures class-body definitions only, so
  ``self.x = ...`` is in source and absent.

This guard is structural, in the style of ``test_edge_counts_prose_conformance``:
it rejects the specific phrasings that claim nonexistence about a symbol, handle
or member, and the "complete over what is written in source" scope claim. A
sentence about a *path* or *file* that doesn't exist is a filesystem fact, not a
resolution claim, so it is out of scope. Free-prose variants beyond these forms
remain review territory.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Surfaces that describe resolution misses or structural-edge completeness to a
# model or a reader. server.py docstrings are the MCP tool descriptions.
SHIPPED_SURFACES = [
    "skills/python-explore/SKILL.md",
    "src/pyeye/mcp/server.py",
    "src/pyeye/mcp/operations/edges.py",
    "src/pyeye/mcp/operations/outline.py",
    "src/pyeye/mcp/operations/inspect.py",
    "src/pyeye/mcp/operations/resolve.py",
    "src/pyeye/mcp/operations/not_found.py",
    "docs/api-redesign.md",
    "README.md",
]

_NONEXISTENCE = re.compile(
    r"\b(?:handle|symbol|member|subclass|attribute|name)s?\b"
    r"[^.;:]{0,40}?\b(?:doesn't|does not|don't|do not) exist\b",
    re.IGNORECASE,
)
_NOT_IN_SOURCE = re.compile(r"not in source", re.IGNORECASE)
_WRITTEN_IN_SOURCE = re.compile(r"complete over what is \*?written in source", re.IGNORECASE)

_PATTERNS = {
    "claims a symbol/handle/member doesn't exist": _NONEXISTENCE,
    'calls an absent member "not in source"': _NOT_IN_SOURCE,
    'claims completeness over "written in source"': _WRITTEN_IN_SOURCE,
}


def nonexistence_claims(text: str) -> list[str]:
    """Return each place ``text`` states a resolution miss or absence as nonexistence."""
    # Backticks, emphasis and line wrapping split phrases; flatten them first.
    flat = " ".join(text.replace("`", "").replace('"', "").split())
    claims: list[str] = []
    for label, pattern in _PATTERNS.items():
        for match in pattern.finditer(flat):
            start = max(0, match.start() - 60)
            claims.append(f"{label}: ...{flat[start : match.end() + 20]}...")
    return claims


# Verbatim from main before #568: each passed CI while contradicting the invariant.
PRE_568_MISSES = {
    "skill not-found bullet": (
        '    `reason: "unresolved"`. That means "this handle doesn\'t exist as written" (often the\n'
        "    right name under the wrong module path), not an empty symbol.\n"
    ),
    "skill static-surface ceiling (scope)": (
        "**Static-surface ceiling.** These structural edges are complete over what is\n"
        "*written in source*, not over what exists at runtime.\n"
    ),
    "skill static-surface ceiling (absence)": (
        'An absent member or subclass means "not in\nsource," **not** "not at runtime"\n'
    ),
    "outline docstring": (
        '    ``DoesNotExist``.  An absent member is "not in source," not "not at runtime."\n'
    ),
}

# Honest phrasings that must stay legal.
HONEST_PROSE = {
    "unresolved is unknown": (
        "That means pyeye couldn't resolve this handle as written: unknown, not evidence "
        "the symbol is absent."
    ),
    "filesystem fact": (
        "The call errors only for invalid arguments or a ``project_path`` that doesn't exist."
    ),
    "missing file": "Raises FileNotFoundError: If file doesn't exist.",
    "measured scope": (
        "An absent member is unknown outside the measured scope, not absent from the code."
    ),
}


@pytest.mark.parametrize("name", sorted(PRE_568_MISSES))
def test_guard_catches_pre_568_prose(name: str) -> None:
    """Each shipped pre-#568 phrasing is flagged, so the guard has teeth."""
    assert nonexistence_claims(PRE_568_MISSES[name]), name


@pytest.mark.parametrize("name", sorted(HONEST_PROSE))
def test_guard_allows_honest_prose(name: str) -> None:
    """Honest phrasings, including filesystem facts, are not flagged."""
    assert nonexistence_claims(HONEST_PROSE[name]) == []


@pytest.mark.parametrize("surface", SHIPPED_SURFACES)
def test_shipped_prose_does_not_claim_nonexistence(surface: str) -> None:
    """No shipped surface describes a miss or an omission as nonexistence."""
    path = REPO_ROOT / surface
    assert path.is_file(), f"{surface} moved; update SHIPPED_SURFACES"
    claims = nonexistence_claims(path.read_text(encoding="utf-8"))
    assert claims == [], f"{surface}:\n" + "\n".join(claims)


def test_invariant_stated_as_general_rule() -> None:
    """The general rule is stated once in the design doc and once in the skill."""
    rule = "is unknown, not absent"
    for surface in ("docs/api-redesign.md", "skills/python-explore/SKILL.md"):
        flat = " ".join((REPO_ROOT / surface).read_text(encoding="utf-8").split())
        assert rule in flat.replace("*", ""), surface
