"""Bind the shipped ``duplication-review`` skill to the CLI it documents (#495).

``python -m pyeye.duplication`` is a documented interface, so the skill's flag
list, defaults, dismissal reasons and filter thresholds must match the code.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from pyeye import duplication as dup

_ROOT = Path(__file__).resolve().parents[1]
_SKILL = _ROOT / "skills" / "duplication-review" / "SKILL.md"
_ARCH = _ROOT / "skills" / "architecture-review"


def _text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _cli_vocabulary() -> set[str]:
    """Subcommand names plus every long option the CLI accepts."""
    parser = dup._parser()
    words: set[str] = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                words.add(name)
                for opt in sub._actions:
                    words.update(o for o in opt.option_strings if o.startswith("--"))
    words.discard("--help")
    return words


def test_frontmatter_names_the_skill() -> None:
    assert re.search(r"^name: duplication-review$", _text(), re.MULTILINE)


def test_documented_flags_match_the_cli_exactly() -> None:
    marker = re.search(r"<!-- duplication-review-flags: (.*?) -->", _text())
    assert marker, "the skill must carry the flag marker comment"
    assert set(marker.group(1).split()) == _cli_vocabulary()


def test_every_flag_is_explained_in_the_body() -> None:
    body = re.sub(r"<!--.*?-->", "", _text(), flags=re.DOTALL)
    for word in _cli_vocabulary():
        assert f"`{word}" in body, f"{word} is not documented in the skill body"


def _default_in_table(flag: str) -> str:
    row = re.search(rf"^\| `{re.escape(flag)}` \| `?([^|`]+)`? \|", _text(), re.MULTILINE)
    assert row, f"no table row for {flag}"
    return row.group(1).strip()


def test_documented_defaults_match_the_code() -> None:
    assert _default_in_table("--min-tokens") == str(dup.DEFAULT_MIN_TOKENS)
    assert _default_in_table("--max-occurrences") == str(dup.DEFAULT_MAX_OCCURRENCES)


def test_dismissal_reasons_match_the_code() -> None:
    line = next(ln for ln in _text().splitlines() if "`--reason` is one of" in ln)
    following = _text().split(line, 1)[1].split("\n\n", 1)[0]
    reasons = re.findall(r"`([a-z-]+)`", line + following)
    assert tuple(r for r in reasons if r != "--reason") == dup.DISMISSAL_REASONS


def test_documented_filter_thresholds_match_the_code() -> None:
    text = _text()
    assert dup.FUNCTION_LINE_SHARE == 0.5 and "more than half the lines" in text
    assert f"{dup.SIGNATURE_LINE_SHARE:.0%}".replace("%", " %") in text


def test_suggested_state_file_is_named() -> None:
    assert ".pyeye/duplication-review.json" in _text()


def test_architecture_review_points_at_this_skill() -> None:
    for name in ("SKILL.md", "auditor.md"):
        assert "duplication-review" in (_ARCH / name).read_text(encoding="utf-8"), name
