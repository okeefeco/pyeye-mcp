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
