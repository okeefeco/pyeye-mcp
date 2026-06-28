"""Anti-drift conformance guard for the shipped ``architecture-review`` skill.

This test binds the user-facing skill (``skills/architecture-review/SKILL.md``)
and the auditor prompt (``skills/architecture-review/auditor.md``) to the
taxonomy module (``pyeye.architecture_review.taxonomy``).  Issue #374 happened
because the skill drifted from the implementation source; this test converts
that drift from a silent rot into a CI failure: if the axis set or output-contract
grades change, the skill and auditor must change too, or this test fails.

Dependency-free by design: stdlib ``re`` + ``pathlib`` only (no yaml).
"""

import re
from pathlib import Path

from pyeye.architecture_review.taxonomy import AXIS_STAKES_PRIOR, SEED_AXES

_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills" / "architecture-review"
SKILL = _SKILLS_DIR / "SKILL.md"
AUDITOR = _SKILLS_DIR / "auditor.md"

_ANCHOR = re.compile(r"<!--\s*architecture-review-axes:\s*(.*?)\s*-->")

_FOUR_GRADES = ("mechanical_fact", "deterministic_single", "ambiguous", "no_signal")


def _skill_text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _auditor_text() -> str:
    return AUDITOR.read_text(encoding="utf-8")


def test_skill_file_exists() -> None:
    """SKILL.md and auditor.md must both exist at the expected paths."""
    assert SKILL.is_file(), f"SKILL.md not found at {SKILL.as_posix()}"
    assert AUDITOR.is_file(), f"auditor.md not found at {AUDITOR.as_posix()}"


def test_anchor_equals_seed_axes() -> None:
    """The embedded anchor in SKILL.md must list exactly the SEED_AXES keys.

    Drift guard: the ``<!-- architecture-review-axes: ... -->`` anchor must track
    ``taxonomy.SEED_AXES`` exactly.  Adding or renaming an axis without updating
    the anchor (or vice-versa) is a CI failure.
    """
    text = _skill_text()
    m = _ANCHOR.search(text)
    assert m is not None, (
        "SKILL.md must embed a "
        "`<!-- architecture-review-axes: ... -->` anchor listing the seed axes"
    )
    documented = set(m.group(1).split())
    assert documented == set(SEED_AXES), (
        f"SKILL.md anchor axes {sorted(documented)} " f"!= SEED_AXES {sorted(SEED_AXES)}"
    )


def test_auditor_mentions_every_seed_axis() -> None:
    """Every key in SEED_AXES must appear somewhere in auditor.md."""
    text = _auditor_text()
    missing = [axis for axis in SEED_AXES if axis not in text]
    assert not missing, f"auditor.md is missing these seed axis keys: {missing}"


def test_auditor_has_no_duplication_axis() -> None:
    """``duplication`` must NOT appear as a backtick-wrapped axis key in auditor.md.

    auditor.md legitimately mentions "duplication" in the carved-out scope caveat
    ("Out of scope — NOT an axis: code duplication").  A blanket substring ban
    would wrongly fail on that legitimate prose.  Instead we assert the
    backtick-wrapped token `` `duplication` `` is absent — that is the encoding
    used for real axis keys in the axis table (e.g. `` `layering` ``).  This
    check PASSES on the current auditor.md (carve-out is plain prose, not a
    table row) and would FAIL if someone added `` `duplication` `` as a table
    axis entry.  We also assert ``duplication`` is absent from SEED_AXES itself.
    """
    text = _auditor_text()
    assert "`duplication`" not in text, (
        "auditor.md must not contain `duplication` as a backtick-wrapped axis key; "
        "code duplication is carved out to #495 and is never a seed axis"
    )
    assert (
        "duplication" not in SEED_AXES
    ), "duplication must not appear in SEED_AXES (tracked separately in #495)"


def test_four_grades_present_in_skill() -> None:
    """All four output-contract grade strings must appear in SKILL.md."""
    text = _skill_text()
    missing = [g for g in _FOUR_GRADES if g not in text]
    assert not missing, f"SKILL.md is missing these output-contract grade strings: {missing}"


def test_axis_stakes_prior_keys_match_seed_axes() -> None:
    """``AXIS_STAKES_PRIOR`` must cover exactly the same keys as ``SEED_AXES``."""
    assert set(AXIS_STAKES_PRIOR) == set(SEED_AXES), (
        f"AXIS_STAKES_PRIOR keys {sorted(AXIS_STAKES_PRIOR)} " f"!= SEED_AXES {sorted(SEED_AXES)}"
    )


def test_skill_name_is_stable() -> None:
    """The frontmatter ``name`` field must be exactly ``architecture-review``.

    The plugin resolves the skill by this name; a rename unships it silently.
    """
    assert re.search(
        r"^name:\s*architecture-review\s*$", _skill_text(), re.MULTILINE
    ), "SKILL.md frontmatter must contain `name: architecture-review`"


def test_skill_declares_a_description() -> None:
    """The frontmatter must include a non-empty ``description`` field."""
    assert re.search(
        r"^description:\s*\S", _skill_text(), re.MULTILINE
    ), "SKILL.md frontmatter must contain a non-empty `description:` field"
