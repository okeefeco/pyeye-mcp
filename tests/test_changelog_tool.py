"""Tests for scripts/changelog.py, the release-PR CHANGELOG tooling (#583)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import scripts.changelog as cl

_ROOT = Path(__file__).resolve().parents[1]


def _log(unreleased: str = "### Fixed\n\n- A fix.\n", *released: tuple[str, str, str]) -> str:
    """Build a CHANGELOG: an [Unreleased] body, then (version, date, body) sections."""
    out = ["# Changelog\n\nIntro.\n\n## [Unreleased]\n\n", unreleased, "\n"]
    for version, date, body in released:
        out += [f"## [{version}] - {date}\n\n", body, "\n"]
    return "".join(out)


_V1 = ("1.0.0", "2025-10-04", "### Added\n\n- First.\n")


class TestParse:
    def test_sections_and_bodies(self):
        sections = cl.parse(_log("### Fixed\n\n- x\n", _V1))
        assert [(s.name, s.date) for s in sections] == [
            ("Unreleased", None),
            ("1.0.0", "2025-10-04"),
        ]
        assert sections[0].body == "### Fixed\n\n- x"

    @pytest.mark.parametrize(
        "heading", ["## v0.1.0 (2025-08-24)", "## 1.0.0", "## [1.0] - 2025-01-01", "## Notes"]
    )
    def test_malformed_heading_rejected(self, heading):
        with pytest.raises(cl.ChangelogError, match="malformed heading"):
            cl.parse(f"## [Unreleased]\n\n{heading}\n\n- x\n")

    def test_subheadings_are_section_content(self):
        assert cl.parse("## [Unreleased]\n\n### BREAKING CHANGES\n\n#### Detail\n")[0].body


class TestVersionKey:
    def test_ordering_includes_prereleases(self):
        order = ["1.9.9", "2.0.0a1", "2.0.0b2", "2.0.0rc1", "2.0.0", "2.0.1", "2.1.0", "10.0.0"]
        scrambled = ["2.0.1", "10.0.0", "2.0.0rc1", "1.9.9", "2.1.0", "2.0.0", "2.0.0b2", "2.0.0a1"]
        assert sorted(scrambled, key=cl.version_key) == order

    @pytest.mark.parametrize("bad", ["v1.0.0", "1.0", "1.0.0.dev1", "latest"])
    def test_rejects_non_versions(self, bad):
        with pytest.raises(cl.ChangelogError):
            cl.version_key(bad)


class TestPrepare:
    def test_promotes_unreleased_and_keeps_an_empty_one(self):
        text = _log("### Fixed\n\n- A fix.\n", _V1)
        out = cl.prepare(text, "1.0.1", ["1.0.0"], "2026-11-07")

        sections = cl.parse(out)
        assert [(s.name, s.date) for s in sections[:2]] == [
            ("Unreleased", None),
            ("1.0.1", "2026-11-07"),
        ]
        assert sections[0].body == ""
        assert sections[1].body == "### Fixed\n\n- A fix."
        assert out.startswith("# Changelog\n\nIntro.\n")  # nothing else touched
        assert cl.check(out, ["1.0.0"]) == []  # result is valid, with 1.0.1 pending

    def test_refuses_empty_unreleased(self):
        with pytest.raises(cl.ChangelogError, match="empty"):
            cl.prepare(_log("", _V1), "1.0.1", ["1.0.0"], "2026-11-07")

    @pytest.mark.parametrize("version", ["1.0.0", "0.9.0"])
    def test_refuses_existing_or_older_versions(self, version):
        with pytest.raises(cl.ChangelogError):
            cl.prepare(_log("- x\n", _V1), version, ["1.0.0"], "2026-11-07")

    def test_refuses_a_version_that_is_only_tagged(self):
        """A tag without a section (the 1.x drift) still counts as released."""
        with pytest.raises(cl.ChangelogError, match="not newer"):
            cl.prepare(_log("- x\n", _V1), "1.1.0", ["1.0.0", "1.1.2"], "2026-11-07")

    @pytest.mark.parametrize(
        ("body", "version", "ok"),
        [
            ("### BREAKING CHANGES\n\n- gone\n", "1.1.0", False),
            ("### BREAKING CHANGES\n\n- gone\n", "2.0.0", True),
            ("### Added\n\n- new\n", "1.0.1", False),
            ("### Added\n\n- new\n", "1.1.0", True),
            ("### Fixed\n\n- fix\n", "1.0.1", True),
            ("### Fixed\n\n- fix\n", "2.0.0", True),  # bigger than needed is allowed
        ],
    )
    def test_bump_level_matches_content(self, body, version, ok):
        args = (_log(body, _V1), version, ["1.0.0"], "2026-11-07")
        if ok:
            cl.prepare(*args)
        else:
            with pytest.raises(cl.ChangelogError, match="needs at least"):
                cl.prepare(*args)

    def test_breaking_before_1_0_needs_only_minor(self):
        text = _log("### BREAKING CHANGES\n\n- x\n", ("0.3.0", "2025-08-27", "- y\n"))
        cl.prepare(text, "0.4.0", ["0.3.0"], "2026-11-07")


class TestNotes:
    def test_returns_section_body(self):
        assert cl.notes(_log("- x\n", _V1), "1.0.0") == "### Added\n\n- First."

    def test_missing_version_errors(self):
        with pytest.raises(cl.ChangelogError, match="no '## \\[9.9.9\\]'"):
            cl.notes(_log("- x\n", _V1), "9.9.9")


class TestPendingRelease:
    _PENDING = _log("", ("2.0.0", "2026-11-07", "- big\n"), _V1)

    def test_release_merge_of_untagged_top_version(self):
        subject = "chore(release): v2.0.0 (#600)"
        assert cl.pending_release(self._PENDING, ["1.0.0"], subject) == "2.0.0"

    @pytest.mark.parametrize(
        "subject",
        [
            "fix: something (#601)",
            "chore(release): v2.0.1",
            "chore(release): v2.0.00",
            "chore: release v2.0.0",
            # the pre-#587 form: not a conventional commit, so it can't be committed
            "release: v2.0.0",
        ],
    )
    def test_non_release_merges_never_tag(self, subject):
        """A stray version heading in an ordinary PR must not publish."""
        assert cl.pending_release(self._PENDING, ["1.0.0"], subject) is None

    def test_merge_commit_of_a_release_pr(self):
        """GitHub's merge-commit format: PR title on the line after the subject (#585)."""
        message = "Merge pull request #600 from okeefeco/release/v2.0.0\n\nchore(release): v2.0.0"
        assert cl.pending_release(self._PENDING, ["1.0.0"], message) == "2.0.0"

    def test_squash_subject_with_a_body(self):
        message = "chore(release): v2.0.0 (#600)\n\n* chore(release): v2.0.0\n\nCo-authored-by: x"
        assert cl.pending_release(self._PENDING, ["1.0.0"], message) == "2.0.0"

    @pytest.mark.parametrize(
        "message",
        [
            # merge commit of an ordinary PR
            "Merge pull request #601 from okeefeco/fix/1-x\n\nfix: something",
            # a squash body that merely mentions the release line
            "fix: something (#601)\n\n* chore(release): v2.0.0",
            # merges that aren't PR merges don't count, even with the line
            "Merge branch 'main' into feature\n\nchore(release): v2.0.0",
            # the release line must be the PR title, not later in the message
            "Merge pull request #600 from okeefeco/release/v2.0.0\n\nchore: x\n\nchore(release): v2.0.0",
        ],
    )
    def test_merge_and_body_lookalikes_never_tag(self, message):
        assert cl.pending_release(self._PENDING, ["1.0.0"], message) is None

    def test_already_tagged_is_a_no_op(self):
        assert (
            cl.pending_release(self._PENDING, ["1.0.0", "2.0.0"], "chore(release): v2.0.0") is None
        )


class TestCheck:
    def test_valid_with_pending_top_release(self):
        text = _log("", ("1.1.0", "2026-01-01", "- y\n"), _V1)
        assert cl.check(text, ["1.0.0"]) == []

    @pytest.mark.parametrize(
        ("text", "tags", "expected"),
        [
            (_log("- x\n", _V1), ["1.0.0", "1.0.1"], "tag v1.0.1 has no"),
            (_log("- x\n", ("1.0.0", "2025-10-04", "")), ["1.0.0"], "has no content"),
            (_log("- x\n", _V1, _V1), ["1.0.0"], "duplicate"),
            (
                _log("- x\n", ("0.1.0", "2025-08-24", "- a\n"), ("0.2.0", "2025-08-25", "- b\n")),
                ["0.1.0", "0.2.0"],
                "out of order",
            ),
            (
                _log(
                    "- x\n", ("1.1.0", "2026-01-01", "- y\n"), ("1.0.5", "2025-12-01", "- z\n"), _V1
                ),
                ["1.0.0"],
                "[1.0.5] has no v1.0.5 tag",
            ),
            ("## [1.0.0] - 2025-10-04\n\n- x\n", ["1.0.0"], "first section must be"),
        ],
    )
    def test_problems_detected(self, text, tags, expected):
        problems = cl.check(text, tags)
        assert any(expected in p for p in problems), problems

    def test_without_tags_skips_tag_rules(self):
        assert cl.check(_log("- x\n", _V1), None) == []


class TestRepoChangelog:
    """The real CHANGELOG.md satisfies the checker, tags included."""

    def test_repo_changelog_is_valid(self):
        tags = cl.git_tag_versions(_ROOT)
        if not tags:
            pytest.skip("no v* tags in this checkout (shallow clone)")
        assert cl.check(cl.CHANGELOG.read_text(encoding="utf-8"), tags) == []

    def test_cli_check_runs_with_bare_python(self):
        """CI runs it with a plain interpreter, before any env is synced."""
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-I", str(_ROOT / "scripts" / "changelog.py"), "check", "--no-tags"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    def test_cli_prepare_writes_the_file(self, tmp_path):
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
        path = tmp_path / "CHANGELOG.md"
        path.write_text(_log("### Fixed\n\n- x\n", _V1))
        code = cl.main(["--changelog", str(path), "prepare", "1.0.1", "--date", "2026-11-07"])
        assert code == 0
        assert "## [1.0.1] - 2026-11-07" in path.read_text()

    def test_cli_outside_a_git_repo_errors_cleanly(self, tmp_path, capsys):
        path = tmp_path / "CHANGELOG.md"
        path.write_text(_log("### Fixed\n\n- x\n", _V1))
        assert cl.main(["--changelog", str(path), "prepare", "1.0.1"]) == 1
        assert "could not list git tags" in capsys.readouterr().err


class TestReleaseTitleIsCommittable:
    """The title ``prepare`` prescribes must pass the repo's commit-msg hook (#587)."""

    def test_release_title_format(self):
        assert cl.release_title("2.0.0") == "chore(release): v2.0.0"

    def test_commitizen_accepts_the_release_title(self, tmp_path):
        msg = tmp_path / "COMMIT_EDITMSG"
        msg.write_text(cl.release_title("2.0.0") + "\n")
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "commitizen", "check", "--commit-msg-file", str(msg)],
            cwd=_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_pending_release_accepts_exactly_the_release_title(self):
        text = _log("", ("2.0.0", "2026-11-07", "- big\n"), _V1)
        assert cl.pending_release(text, ["1.0.0"], cl.release_title("2.0.0")) == "2.0.0"


# ---------------------------------------------------------------------------
# Changelog fragments (#660): PRs add changes/<issue>.<category>.md instead of
# editing [Unreleased]; prepare assembles them at release time.
# ---------------------------------------------------------------------------


def _frags(tmp_path: Path, files: dict[str, str]) -> Path:
    d = tmp_path / "changes"
    d.mkdir(exist_ok=True)
    for name, text in files.items():
        (d / name).write_text(text)
    return d


class TestFragmentNames:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("619.fixed.md", (619, 0, "fixed")),
            ("623-2.fixed.md", (623, 2, "fixed")),
            ("660.breaking.md", (660, 0, "breaking")),
            ("12.security.md", (12, 0, "security")),
        ],
    )
    def test_valid(self, name, expected):
        assert cl.parse_fragment_name(name) == expected

    @pytest.mark.parametrize(
        "name",
        [
            "619.fix.md",  # unknown category
            "619.Fixed.md",  # categories are lower-case
            "fixed.md",
            "abc.fixed.md",
            "619.fixed.txt",
            "619-.fixed.md",
            "619.fixed.extra.md",
        ],
    )
    def test_invalid(self, name):
        with pytest.raises(cl.ChangelogError):
            cl.parse_fragment_name(name)

    def test_every_category_has_a_heading_in_release_order(self):
        assert list(cl.CATEGORIES) == [
            "breaking",
            "added",
            "changed",
            "deprecated",
            "removed",
            "fixed",
            "security",
        ]
        assert cl.CATEGORIES["breaking"] == "BREAKING CHANGES"


class TestFragmentProblems:
    def test_clean_directory(self, tmp_path):
        d = _frags(tmp_path, {"1.fixed.md": "- a\n", "README.md": "# About\n"})
        assert cl.fragment_problems(d) == []

    def test_missing_directory_is_fine(self, tmp_path):
        assert cl.fragment_problems(tmp_path / "changes") == []

    def test_reports_every_problem(self, tmp_path):
        d = _frags(
            tmp_path,
            {
                "1.fix.md": "- a\n",
                "2.fixed.md": "",
                "3.fixed.md": "just prose\n",
                "4.added.md": "- a\n\n### Sneaky\n\n- b\n",
                "notes.txt": "x",
            },
        )
        problems = "\n".join(cl.fragment_problems(d))
        assert "1.fix.md" in problems and "unknown category 'fix'" in problems
        assert "2.fixed.md" in problems and "empty" in problems
        assert "3.fixed.md" in problems and "'- '" in problems
        assert "4.added.md" in problems and "heading" in problems
        assert "notes.txt" in problems

    def test_read_fragments_sorts_by_issue_then_suffix(self, tmp_path):
        d = _frags(
            tmp_path,
            {"20.fixed.md": "- c\n", "3-2.fixed.md": "- b\n", "3.fixed.md": "- a\n"},
        )
        assert [f.path.name for f in cl.read_fragments(d)] == [
            "3.fixed.md",
            "3-2.fixed.md",
            "20.fixed.md",
        ]

    def test_read_fragments_refuses_a_bad_directory(self, tmp_path):
        d = _frags(tmp_path, {"1.oops.md": "- a\n"})
        with pytest.raises(cl.ChangelogError, match="1.oops.md"):
            cl.read_fragments(d)


class TestPrepareWithFragments:
    def _prepare(self, tmp_path, unreleased, files, version="1.1.0"):
        d = _frags(tmp_path, files)
        text = _log(unreleased, _V1)
        return cl.prepare(text, version, ["1.0.0"], "2026-11-20", cl.read_fragments(d))

    def test_collects_fragments_into_headings_in_release_order(self, tmp_path):
        out = self._prepare(
            tmp_path,
            "",
            {
                "5.fixed.md": "- Fix five.\n",
                "2.added.md": "- Add two.\n",
                "9.security.md": "- Secure nine.\n",
                "3.changed.md": "- Change three.\n",
            },
        )
        released_body = cl.parse(out)[1].body
        assert released_body == (
            "### Added\n\n- Add two.\n\n"
            "### Changed\n\n- Change three.\n\n"
            "### Fixed\n\n- Fix five.\n\n"
            "### Security\n\n- Secure nine."
        )
        assert cl.parse(out)[0].body == ""

    def test_existing_bullets_come_first_and_are_kept_verbatim(self, tmp_path):
        existing = "### Fixed\n\n- Old fix.\n  More detail.\n\n### Added\n\n- Old add.\n"
        out = self._prepare(
            tmp_path, existing, {"7.fixed.md": "- New fix.\n", "8.added.md": "- New add.\n"}
        )
        assert cl.parse(out)[1].body == (
            "### Added\n\n- Old add.\n- New add.\n\n"
            "### Fixed\n\n- Old fix.\n  More detail.\n- New fix."
        )

    def test_several_bullets_and_suffixed_fragments(self, tmp_path):
        out = self._prepare(
            tmp_path,
            "",
            {"4-2.fixed.md": "- Second PR.\n", "4.fixed.md": "- One.\n- Two.\n"},
        )
        assert cl.parse(out)[1].body == "### Fixed\n\n- One.\n- Two.\n- Second PR."

    def test_unknown_existing_heading_is_kept_after_the_known_ones(self, tmp_path):
        out = self._prepare(tmp_path, "### Notes\n\n- A note.\n", {"1.added.md": "- New.\n"})
        assert cl.parse(out)[1].body == "### Added\n\n- New.\n\n### Notes\n\n- A note."

    def test_fragments_alone_are_enough_to_release(self, tmp_path):
        out = self._prepare(tmp_path, "", {"1.fixed.md": "- Fix.\n"}, version="1.0.1")
        assert cl.check(out, ["1.0.0"]) == []

    def test_nothing_at_all_is_refused(self, tmp_path):
        with pytest.raises(cl.ChangelogError, match="empty"):
            self._prepare(tmp_path, "", {})

    def test_breaking_fragment_needs_a_major_bump(self, tmp_path):
        with pytest.raises(cl.ChangelogError, match="BREAKING CHANGES"):
            self._prepare(tmp_path, "", {"1.breaking.md": "- Gone.\n"}, version="1.1.0")
        out = self._prepare(tmp_path, "", {"1.breaking.md": "- Gone.\n"}, version="2.0.0")
        assert cl.parse(out)[1].body.startswith("### BREAKING CHANGES\n\n- Gone.")

    def test_added_fragment_needs_a_minor_bump(self, tmp_path):
        with pytest.raises(cl.ChangelogError, match="needs at least a minor"):
            self._prepare(tmp_path, "", {"1.added.md": "- New.\n"}, version="1.0.1")

    def test_later_sections_are_untouched(self, tmp_path):
        d = _frags(tmp_path, {"1.fixed.md": "- Fix.\n"})
        v0 = ("0.9.0", "2025-01-01", "### Fixed\n\n- Ancient.\n")
        text = _log("", _V1, v0)
        out = cl.prepare(text, "1.0.1", ["1.0.0", "0.9.0"], "2026-11-20", cl.read_fragments(d))
        tail = text[text.index("## [1.0.0]") :]
        assert out.endswith(tail)


class TestNoBreaking:
    """The v2.x guard: nothing pending may be a breaking change."""

    def test_clean(self, tmp_path):
        d = _frags(tmp_path, {"1.fixed.md": "- a\n"})
        assert cl.breaking_pending(_log("### Fixed\n\n- x\n", _V1), d) == []

    def test_unreleased_heading(self, tmp_path):
        found = cl.breaking_pending(_log("### BREAKING CHANGES\n\n- x\n", _V1), tmp_path)
        assert len(found) == 1 and "[Unreleased]" in found[0]

    def test_released_breaking_sections_do_not_count(self, tmp_path):
        v1 = ("1.0.0", "2025-10-04", "### BREAKING CHANGES\n\n- old\n")
        assert cl.breaking_pending(_log("### Fixed\n\n- x\n", v1), tmp_path) == []

    def test_breaking_fragment_even_if_misnamed_otherwise(self, tmp_path):
        d = _frags(tmp_path, {"1.breaking.md": "- a\n", "x-y.breaking.md": "- b\n"})
        found = cl.breaking_pending(_log("### Fixed\n\n- x\n", _V1), d)
        assert sorted(found) == ["changes/1.breaking.md", "changes/x-y.breaking.md"]

    def test_cli_prints_count_and_exit_code(self, tmp_path, capsys):
        path = tmp_path / "CHANGELOG.md"
        path.write_text(_log("### Fixed\n\n- x\n", _V1))
        assert cl.main(["--changelog", str(path), "no-breaking"]) == 0
        assert capsys.readouterr().out.strip() == "0"
        _frags(tmp_path, {"3.breaking.md": "- gone\n"})
        assert cl.main(["--changelog", str(path), "no-breaking"]) == 1
        captured = capsys.readouterr()
        assert captured.out.strip() == "1"
        assert "3.breaking.md" in captured.err


class TestFragmentCli:
    def test_prepare_assembles_and_deletes_fragments(self, tmp_path):
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
        path = tmp_path / "CHANGELOG.md"
        path.write_text(_log("", _V1))
        d = _frags(tmp_path, {"1.fixed.md": "- Fix.\n", "README.md": "# Fragments\n"})
        code = cl.main(["--changelog", str(path), "prepare", "1.0.1", "--date", "2026-11-20"])
        assert code == 0
        assert "## [1.0.1] - 2026-11-20\n\n### Fixed\n\n- Fix." in path.read_text()
        assert sorted(p.name for p in d.iterdir()) == ["README.md"]

    def test_prepare_with_a_bad_fragment_changes_nothing(self, tmp_path, capsys):
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
        path = tmp_path / "CHANGELOG.md"
        before = _log("### Fixed\n\n- x\n", _V1)
        path.write_text(before)
        d = _frags(tmp_path, {"1.fixed.md": "- ok\n", "2.nope.md": "- bad\n"})
        assert cl.main(["--changelog", str(path), "prepare", "1.0.1"]) == 1
        assert path.read_text() == before
        assert sorted(p.name for p in d.iterdir()) == ["1.fixed.md", "2.nope.md"]
        assert "2.nope.md" in capsys.readouterr().err

    def test_check_reports_fragment_problems(self, tmp_path, capsys):
        path = tmp_path / "CHANGELOG.md"
        path.write_text(_log("### Fixed\n\n- x\n", _V1))
        _frags(tmp_path, {"1.fix.md": "- a\n"})
        assert cl.main(["--changelog", str(path), "check", "--no-tags"]) == 1
        assert "changes/1.fix.md" in capsys.readouterr().err

    def test_repo_fragments_are_valid(self):
        assert cl.fragment_problems(_ROOT / "changes") == []


class TestFactLedgerStamp:
    """prepare stamps the release into the docs-facts ledgers (#826)."""

    _REMOVED = (
        '{\n  "removed": [\n'
        '    {"fact_id": "tool.a", "match": "word", "removed_in": "unreleased"},\n'
        '    {"fact_id": "tool.b", "match": "word", "removed_in": "2.0.0",'
        ' "note": "was unreleased"}\n  ]\n}\n'
    )

    def test_stamp_changes_only_the_release_values(self):
        stamped = cl.stamp_unreleased(self._REMOVED, "2.1.1")
        assert '"removed_in": "2.1.1"' in stamped
        assert '"note": "was unreleased"' in stamped
        assert '"removed_in": "2.0.0"' in stamped
        assert cl.stamp_unreleased('{"first_seen": "unreleased"}', "3.0.0") == (
            '{"first_seen": "3.0.0"}'
        )

    def test_prepare_stamps_the_ledgers_and_check_still_passes(self, tmp_path, capsys):
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
        path = tmp_path / "CHANGELOG.md"
        path.write_text(_log("", _V1))
        _frags(tmp_path, {"1.fixed.md": "- Fix.\n"})
        facts = tmp_path / "docs" / "facts"
        facts.mkdir(parents=True)
        (facts / "removed.json").write_text(self._REMOVED, encoding="utf-8")
        (facts / "uncovered.json").write_text(
            '{"baseline": [], "new": [{"fact_id": "x", "first_seen": "unreleased"}]}\n',
            encoding="utf-8",
        )

        assert cl.main(["--changelog", str(path), "prepare", "1.0.1", "--date", "2026-11-20"]) == 0

        assert '"removed_in": "1.0.1"' in (facts / "removed.json").read_text(encoding="utf-8")
        assert '"first_seen": "1.0.1"' in (facts / "uncovered.json").read_text(encoding="utf-8")
        out = capsys.readouterr().out
        assert "Stamped 1.0.1 into docs/facts/removed.json." in out
        assert "Stamped 1.0.1 into docs/facts/uncovered.json." in out
        assert cl.main(["--changelog", str(path), "check", "--no-tags"]) == 0

    def test_prepare_without_ledgers_is_a_clean_no_op(self, tmp_path, capsys):
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
        path = tmp_path / "CHANGELOG.md"
        path.write_text(_log("", _V1))
        _frags(tmp_path, {"1.fixed.md": "- Fix.\n"})

        assert cl.main(["--changelog", str(path), "prepare", "1.0.1"]) == 0
        assert "Stamped" not in capsys.readouterr().out
        assert not (tmp_path / "docs").exists()

    def test_the_ledger_list_names_the_files_docs_facts_writes(self):
        from pyeye.docs_facts import ledger, removed

        assert set(cl.FACT_LEDGERS) == {removed.REMOVED, ledger.UNCOVERED}
