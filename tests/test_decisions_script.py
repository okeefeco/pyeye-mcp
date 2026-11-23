"""The decision log is one file per decision, with no committed index (#679).

``pyeye.decisions`` (shipped since #1093; this repo's ``scripts/decisions.py``
wraps it) lists entries from their front matter (``index``), validates them
(``check``, run in CI) and splits entries still written into ``DECISIONS.md``
into files (``migrate``, re-runnable and idempotent). The engine is tested
through the module; this repo's own log through the wrapper's settings.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from pyeye import decisions

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("decisions_repo", _ROOT / "scripts" / "decisions.py")
assert _spec and _spec.loader
repo = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = repo
_spec.loader.exec_module(repo)


def _entry(
    directory: Path,
    name: str,
    *,
    title: str = "A decision (#1)",
    date: str | None = None,
    issues: list[int] | None = None,
    anchors: list[str] | None = None,
    status: str = "active",
    applies_to: str | None = "`pkg.mod.Thing` and `pkg.mod.Other`",
    **links: list[str],
) -> Path:
    date = date or name[:10]
    meta = {
        "date": date,
        "title": title,
        "issues": [1] if issues is None else issues,
        "anchors": anchors or ["pkg.mod.Thing"],
        "status": status,
        "amends": links.get("amends", []),
        "supersedes": links.get("supersedes", []),
        "amended_by": links.get("amended_by", []),
        "superseded_by": links.get("superseded_by", []),
    }
    body = f"## {date} — {title}\n\n**Friction:** x\n**Decision:** y\n**Anchor:** `pkg.mod.Thing`\n"
    if applies_to is not None:
        body += f"**Applies-to:** {applies_to}\n"
    body += "**Verify:** unverifiable — test fixture.\n"
    path = directory / name
    path.write_text(decisions.render(meta, body), encoding="utf-8", newline="\n")
    return path


def _problems(directory: Path) -> list[str]:
    entries, errors = decisions.load(directory)
    return errors + decisions.check(entries)


# ---------------------------------------------------------------------------
# The repository's own log
# ---------------------------------------------------------------------------


def test_the_repository_log_is_valid() -> None:
    entries, errors = decisions.load(repo.ENTRIES_DIR)
    assert not errors
    assert not decisions.check(entries, repo.APPLIES_TO_GRANDFATHERED)
    assert not decisions.stale_grandfathered(entries, repo.APPLIES_TO_GRANDFATHERED)
    assert len(entries) >= 53


def test_decisions_md_is_a_static_header_with_no_entries() -> None:
    text = repo.LOG_FILE.read_text(encoding="utf-8")
    assert decisions.entries_in_log(text) == []
    assert text == repo.STATIC_HEADER


def test_the_append_only_decision_is_superseded_by_679() -> None:
    entries = {e.name: e for e in decisions.load(repo.ENTRIES_DIR)[0]}
    old = entries["2026-06-13-decisions-captured-as-an-append-only-log-not-one-adr-file.md"]
    new = entries["2026-11-15-679-one-file-per-decision-with-no-committed-index.md"]
    assert old.status == "superseded"
    assert old.meta["superseded_by"] == [new.name]
    assert new.meta["supersedes"] == [old.name]


def test_the_skill_documents_the_entry_files() -> None:
    skill = (_ROOT / ".claude" / "skills" / "decision-log" / "SKILL.md").read_text(encoding="utf-8")
    assert "docs/decisions/entries/" in skill
    assert "python -m pyeye.decisions check" in skill  # the shipped module (#1093)
    assert "Append on confirm" not in skill


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def test_a_valid_pair_with_symmetric_links_passes(tmp_path: Path) -> None:
    _entry(tmp_path, "2026-01-01-1-old.md", status="amended", amended_by=["2026-02-01-2-new.md"])
    _entry(
        tmp_path,
        "2026-02-01-2-new.md",
        title="New (#2)",
        issues=[2],
        amends=["2026-01-01-1-old.md"],
    )
    assert _problems(tmp_path) == []


def test_issueless_names_are_allowed(tmp_path: Path) -> None:
    _entry(tmp_path, "2026-01-01-a-process-rule.md", issues=[])
    assert _problems(tmp_path) == []


def test_a_dangling_link_is_reported(tmp_path: Path) -> None:
    _entry(tmp_path, "2026-01-01-1-a.md", amends=["2025-01-01-9-missing.md"])
    assert any("doesn't exist" in p for p in _problems(tmp_path))


def test_an_asymmetric_link_is_reported(tmp_path: Path) -> None:
    _entry(tmp_path, "2026-01-01-1-old.md")
    _entry(tmp_path, "2026-02-01-2-new.md", issues=[2], supersedes=["2026-01-01-1-old.md"])
    problems = _problems(tmp_path)
    assert any("superseded_by doesn't list" in p for p in problems)


def test_status_must_follow_the_links(tmp_path: Path) -> None:
    _entry(tmp_path, "2026-01-01-1-old.md", superseded_by=["2026-02-01-2-new.md"])
    _entry(tmp_path, "2026-02-01-2-new.md", issues=[2], supersedes=["2026-01-01-1-old.md"])
    assert any("its links make it 'superseded'" in p for p in _problems(tmp_path))


@pytest.mark.parametrize(
    ("name", "kwargs", "expected"),
    [
        ("2026-01-01-1-a.md", {"date": "2026-01-02"}, "differs from front-matter date"),
        ("2026-01-01-1-a.md", {"issues": [7]}, "name's issue #1 is not in issues"),
        ("2026-01-01-1-a.md", {"status": "retired"}, "status must be one of"),
        ("2026-01-01-1-a.md", {"issues": ["1"]}, "issues must be a list of positive ints"),
        ("2026-01-01-1-Bad_Slug.md", {}, "name must be"),
        ("notes.md", {"date": "2026-01-01"}, "name must be"),
    ],
)
def test_bad_front_matter_is_reported(
    tmp_path: Path, name: str, kwargs: dict, expected: str
) -> None:
    _entry(tmp_path, name, **kwargs)
    assert any(expected in p for p in _problems(tmp_path)), _problems(tmp_path)


def test_missing_and_unknown_keys(tmp_path: Path) -> None:
    (tmp_path / "2026-01-01-1-a.md").write_text(
        '---\ndate: "2026-01-01"\ncolour: "red"\n---\n\n## 2026-01-01 — x\n',
        encoding="utf-8",
        newline="\n",
    )
    problems = _problems(tmp_path)
    assert any("missing front-matter keys" in p for p in problems)
    assert any("unknown front-matter keys ['colour']" in p for p in problems)


def test_heading_must_match_front_matter(tmp_path: Path) -> None:
    path = _entry(tmp_path, "2026-01-01-1-a.md")
    text = path.read_text(encoding="utf-8")
    text = text.replace("## 2026-01-01 — A decision", "## 2026-01-01 — Other")
    path.write_text(text, encoding="utf-8", newline="\n")
    assert any("body heading doesn't match" in p for p in _problems(tmp_path))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("no front matter\n", "must start with a '---'"),
        ('---\ndate: "x"\n', "not closed"),
        ('---\ndate "x"\n---\n', "expected 'key: <JSON value>'"),
        ("---\ndate: x\n---\n", "is not a JSON value"),
        ('---\ndate: "a"\ndate: "b"\n---\n', "duplicate key"),
    ],
)
def test_unparseable_files_are_errors(tmp_path: Path, text: str, expected: str) -> None:
    (tmp_path / "2026-01-01-1-a.md").write_text(text, encoding="utf-8", newline="\n")
    assert any(expected in p for p in _problems(tmp_path))


def test_check_cli_hints_at_migrate_for_entries_left_in_the_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    entries = tmp_path / "entries"
    entries.mkdir()
    log = tmp_path / "DECISIONS.md"
    log.write_text(
        decisions.STATIC_HEADER + "\n## 2026-03-01 — Late entry (#5)\n\nbody\n",
        encoding="utf-8",
        newline="\n",
    )
    # The repo wrapper names its own command; the module names `python -m pyeye.decisions`.
    assert repo.main(["--dir", str(entries), "--log", str(log), "check"]) == 1
    assert "python scripts/decisions.py migrate" in capsys.readouterr().err
    assert decisions.main(["--dir", str(entries), "--log", str(log), "check"]) == 1
    assert "python -m pyeye.decisions migrate" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# index
# ---------------------------------------------------------------------------


def test_index_filters_and_orders(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _entry(
        tmp_path, "2026-01-01-1-old.md", superseded_by=["2026-02-01-2-new.md"], status="superseded"
    )
    _entry(
        tmp_path,
        "2026-02-01-2-new.md",
        title="New (#2)",
        issues=[2],
        anchors=["pyeye.resolver.resolve_handle"],
        supersedes=["2026-01-01-1-old.md"],
    )
    entries, _ = decisions.load(tmp_path)

    assert [e.name for e in decisions.select(entries)] == [
        "2026-02-01-2-new.md",
        "2026-01-01-1-old.md",
    ]
    assert [e.name for e in decisions.select(entries, active=True)] == ["2026-02-01-2-new.md"]
    assert [e.name for e in decisions.select(entries, symbol="resolve_handle")] == [
        "2026-02-01-2-new.md"
    ]
    assert [e.name for e in decisions.select(entries, issue=1)] == ["2026-01-01-1-old.md"]
    assert [e.name for e in decisions.select(entries, status="superseded")] == [
        "2026-01-01-1-old.md"
    ]

    assert decisions.main(["--dir", str(tmp_path), "index", "--issue", "2"]) == 0
    out = capsys.readouterr().out
    assert "| 2026-02-01 | New (#2) | #2 |" in out
    assert "old.md" not in out


# ---------------------------------------------------------------------------
# migrate
# ---------------------------------------------------------------------------


_LOG_ENTRY = """## 2026-03-02 — Second rule; amends the first (#9)

**Friction:** a
**Decision:** b, amending the 2026-03-01 entry.
**Anchor:** `pkg.second` ; #9
**Applies-to:** `pkg.second`
**Verify:** c

"""
_LOG_ENTRY_2 = """## 2026-03-01 — First rule (#8)

**Friction:** a
**Anchor:** `pkg.first`
"""


def test_migrate_splits_verifies_and_is_idempotent(tmp_path: Path) -> None:
    entries = tmp_path / "entries"
    log = tmp_path / "DECISIONS.md"
    log.write_text("# Old header\n\n" + _LOG_ENTRY + _LOG_ENTRY_2, encoding="utf-8", newline="\n")

    notes = decisions.migrate(log, entries)

    names = sorted(p.name for p in entries.iterdir())
    assert names == ["2026-03-01-8-first-rule.md", "2026-03-02-9-second-rule-amends-the-first.md"]
    assert any("link it: 2026-03-02-9" in n for n in notes)
    assert log.read_text(encoding="utf-8") == decisions.STATIC_HEADER
    second = decisions.parse(names[1], (entries / names[1]).read_text(encoding="utf-8"))
    assert second.body == _LOG_ENTRY.rstrip("\n") + "\n"  # verbatim
    assert second.meta["issues"] == [9] and second.meta["anchors"] == ["pkg.second"]
    # A migrated entry is new to this log, so it needs Applies-to too (#636).
    (problem,) = _problems(entries)
    assert problem.startswith("2026-03-01-8-first-rule.md: missing '**Applies-to:**'")

    # Re-running, or re-running after a merge brings the same entries back, changes nothing.
    log.write_text(decisions.STATIC_HEADER + "\n" + _LOG_ENTRY_2, encoding="utf-8", newline="\n")
    before = {p.name: p.read_text(encoding="utf-8") for p in entries.iterdir()}
    notes = decisions.migrate(log, entries)
    assert {p.name: p.read_text(encoding="utf-8") for p in entries.iterdir()} == before
    assert any(n.startswith("unchanged: 2026-03-01-8-first-rule.md") for n in notes)


def test_migrate_refuses_to_overwrite_a_different_body(tmp_path: Path) -> None:
    entries = tmp_path / "entries"
    log = tmp_path / "DECISIONS.md"
    log.write_text(_LOG_ENTRY_2, encoding="utf-8", newline="\n")
    decisions.migrate(log, entries)
    log.write_text(
        _LOG_ENTRY_2.replace("**Friction:** a", "**Friction:** changed"),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(decisions.EntryError, match="different body"):
        decisions.migrate(log, entries)
    assert "changed" not in (entries / "2026-03-01-8-first-rule.md").read_text(encoding="utf-8")
    assert decisions.main(["--dir", str(entries), "--log", str(log), "migrate"]) == 1


def test_migrate_with_nothing_to_do(tmp_path: Path) -> None:
    entries = tmp_path / "entries"
    entries.mkdir()
    log = tmp_path / "DECISIONS.md"
    log.write_text(decisions.STATIC_HEADER, encoding="utf-8", newline="\n")
    assert decisions.migrate(log, entries)[-1] == "0 entries in DECISIONS.md, 0 split out"


def test_migrate_update_takes_the_log_body_and_keeps_front_matter(tmp_path: Path) -> None:
    entries = tmp_path / "entries"
    log = tmp_path / "DECISIONS.md"
    log.write_text(_LOG_ENTRY_2, encoding="utf-8", newline="\n")
    decisions.migrate(log, entries)
    path = entries / "2026-03-01-8-first-rule.md"
    edited = _LOG_ENTRY_2.replace("**Friction:** a", "**Friction:** amended later")
    log.write_text(edited, encoding="utf-8", newline="\n")

    notes = decisions.migrate(log, entries, update=True)

    assert "updated body: 2026-03-01-8-first-rule.md" in notes
    entry = decisions.parse(path.name, path.read_text(encoding="utf-8"))
    assert entry.body == edited.rstrip("\n") + "\n"
    assert entry.meta["issues"] == [8]
    assert log.read_text(encoding="utf-8") == decisions.STATIC_HEADER


def test_index_prints_non_ascii_titles_on_a_cp1252_console(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows consoles default to cp1252, which can't encode ``↔`` (#679, Windows CI)."""
    import io

    _entry(tmp_path, "2026-01-01-1-a.md", title="One file↔module mapper · roots — policy (#1)")
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252"))
    assert decisions.main(["--dir", str(tmp_path), "index"]) == 0
    sys.stdout.flush()
    assert "file↔module" in raw.getvalue().decode("utf-8")


def test_written_entries_use_lf_line_endings(tmp_path: Path) -> None:
    """Byte-for-byte checks need LF everywhere, even where the OS default is CRLF."""
    log = tmp_path / "DECISIONS.md"
    log.write_text(_LOG_ENTRY_2, encoding="utf-8", newline="\n")
    decisions.migrate(log, tmp_path / "entries")
    for path in [log, *(tmp_path / "entries").iterdir()]:
        assert b"\r\n" not in path.read_bytes(), path.name


# ---------------------------------------------------------------------------
# Applies-to is mandatory for new entries (#636)
# ---------------------------------------------------------------------------


def _applies_problems(directory: Path, grandfathered: frozenset[str] = frozenset()) -> list[str]:
    entries, errors = decisions.load(directory)
    assert not errors
    return [p for p in decisions.check(entries, grandfathered) if "Applies-to" in p]


def test_a_new_entry_without_applies_to_fails(tmp_path: Path) -> None:
    _entry(tmp_path, "2026-12-01-9-new.md", applies_to=None)

    (problem,) = _applies_problems(tmp_path)
    assert "2026-12-01-9-new.md: missing '**Applies-to:**' (#636)" in problem
    assert "none (<why>)" in problem


@pytest.mark.parametrize(
    "value",
    [
        "`pkg.mod.Thing`",
        "none (policy decision)",
        "None (a release-process rule; no code site)",
        "every caller of `resolve_handle`; see the fitness test",
    ],
)
def test_valid_applies_to_values_pass(tmp_path: Path, value: str) -> None:
    _entry(tmp_path, "2026-12-01-9-new.md", applies_to=value)

    assert not _applies_problems(tmp_path)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", "says nothing"),
        ("n/a", "says nothing"),
        ("N/A.", "says nothing"),
        ("none", "says nothing"),
        ("TBD", "says nothing"),
        ("none — policy", "must read 'none (<why>)'"),
        ("none ()", "must read 'none (<why>)'"),
    ],
)
def test_empty_or_placeholder_applies_to_fails(tmp_path: Path, value: str, expected: str) -> None:
    _entry(tmp_path, "2026-12-01-9-new.md", applies_to=value)

    (problem,) = _applies_problems(tmp_path)
    assert expected in problem


def test_a_list_on_the_following_lines_counts(tmp_path: Path) -> None:
    path = _entry(tmp_path, "2026-12-01-9-new.md", applies_to=None)
    text = path.read_text(encoding="utf-8").replace(
        "**Verify:**", "**Applies-to:**\n\n- `pkg.a`\n- `pkg.b`\n\n**Verify:**"
    )
    path.write_text(text, encoding="utf-8", newline="\n")

    assert not _applies_problems(tmp_path)
    entries, _ = decisions.load(tmp_path)
    assert decisions.applies_to(entries[0].body) == "- `pkg.a` - `pkg.b`"


def test_an_empty_label_followed_by_the_next_field_fails(tmp_path: Path) -> None:
    path = _entry(tmp_path, "2026-12-01-9-new.md", applies_to=None)
    text = path.read_text(encoding="utf-8").replace("**Verify:**", "**Applies-to:**\n**Verify:**")
    path.write_text(text, encoding="utf-8", newline="\n")

    (problem,) = _applies_problems(tmp_path)
    assert "says nothing" in problem


def test_a_grandfathered_entry_may_lack_applies_to(tmp_path: Path) -> None:
    _entry(tmp_path, "2026-01-01-1-old.md", applies_to=None)

    assert not _applies_problems(tmp_path, frozenset({"2026-01-01-1-old.md"}))


def test_a_grandfathered_entry_that_gains_applies_to_must_leave_the_list(tmp_path: Path) -> None:
    _entry(tmp_path, "2026-01-01-1-old.md")

    (problem,) = _applies_problems(tmp_path, frozenset({"2026-01-01-1-old.md"}))
    assert "delete it from APPLIES_TO_GRANDFATHERED" in problem


def test_a_grandfathered_name_with_no_file_is_stale(tmp_path: Path) -> None:
    _entry(tmp_path, "2026-01-01-1-old.md", applies_to=None)
    entries, _ = decisions.load(tmp_path)

    stale = decisions.stale_grandfathered(
        entries, frozenset({"2026-01-01-1-old.md", "2026-01-01-1-gone.md"})
    )
    assert stale == [
        "APPLIES_TO_GRANDFATHERED lists '2026-01-01-1-gone.md', which doesn't exist; delete it"
    ]


def test_the_grandfather_list_holds_only_entries_without_applies_to() -> None:
    """The real list: every name exists, and none of them has Applies-to."""
    entries, _ = decisions.load(repo.ENTRIES_DIR)
    by_name = {e.name: e for e in entries}
    for name in repo.APPLIES_TO_GRANDFATHERED:
        assert name in by_name, name
        assert decisions.applies_to(by_name[name].body) is None, name


def test_check_cli_fails_a_new_entry_without_applies_to(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    entries = tmp_path / "entries"
    entries.mkdir()
    _entry(entries, "2026-12-01-9-new.md", applies_to=None)

    # This repo's grandfather list (the wrapper's), checked against a log that lacks them.
    code = repo.main(["--dir", str(entries), "--log", str(tmp_path / "none.md"), "check"])

    err = capsys.readouterr().err
    assert code == 1
    assert "missing '**Applies-to:**'" in err
    # The real grandfather list is stale against this toy directory, and says so.
    assert "APPLIES_TO_GRANDFATHERED lists" in err
