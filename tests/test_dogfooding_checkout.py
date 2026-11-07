"""Tests for the ``start-on-checkout`` metrics command (#462).

This command is wired as a pre-commit ``post-checkout`` hook so that switching
to an issue-numbered branch auto-starts a dogfooding metrics session. It
replaces the old, uncommitted ``.git/hooks/post-checkout`` that only ran on one
developer's machine and shelled out with a bare ``python`` interpreter.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import click.testing
import pytest

import scripts.dogfooding_metrics as dm

# Branch name → expected issue number, shared by the Python and shell parsers.
_BRANCH_CASES = [
    ("chore/462-pre-commit-managed-hooks", 462),
    ("feat/23-add-validation", 23),
    ("fix/7", 7),
    # Flat forms: native EnterWorktree without the naming hook.
    ("feat-474-outline-depth-1-default", 474),
    ("worktree-feat-474-outline-depth-1-default", 474),
    ("main", None),
    ("develop", None),
    ("", None),
    # Regressions for #576: digits that are not an issue number.
    ("worktree-bridge-cse_01Ns43uuZJsXcxcS7AZGV8dn", None),  # pragma: allowlist secret
    ("dependabot-uv-fastmcp-4.1.3", None),
    ("release/v1.1.3", None),
    ("feat/v2-redesign", None),
    ("fix/12abc", None),
]


class TestExtractIssue:
    """Branch-name → issue-number parsing for ``type/<issue>-description`` branches.

    Only the documented convention yields an issue (#576). Digits elsewhere in a
    branch name (session IDs, version numbers) must not start a session against
    the wrong issue.
    """

    @pytest.mark.parametrize(
        ("branch", "expected"),
        _BRANCH_CASES,
    )
    def test_extract_issue(self, branch, expected):
        assert dm._extract_issue(branch) == expected


class _RecordingMetrics:
    """Stand-in for DogfoodingMetrics that records start_session calls only."""

    started: list[int | None] = []

    def __init__(self, *args, **kwargs):
        pass

    def start_session(self, issue_number=None):
        type(self).started.append(issue_number)
        return {"id": "test", "issue": issue_number}


@pytest.fixture
def recording(monkeypatch):
    _RecordingMetrics.started = []
    monkeypatch.setattr(dm, "DogfoodingMetrics", _RecordingMetrics)
    return _RecordingMetrics


def _invoke(monkeypatch, *, branch, checkout_type):
    monkeypatch.setattr(dm, "_current_branch", lambda: branch)
    if checkout_type is None:
        monkeypatch.delenv("PRE_COMMIT_CHECKOUT_TYPE", raising=False)
    else:
        monkeypatch.setenv("PRE_COMMIT_CHECKOUT_TYPE", checkout_type)
    return click.testing.CliRunner().invoke(dm.cli, ["start-on-checkout"])


class TestStartOnCheckout:
    def test_starts_session_on_issue_branch(self, monkeypatch, recording):
        result = _invoke(monkeypatch, branch="chore/462-x", checkout_type="1")
        assert result.exit_code == 0
        assert recording.started == [462]

    def test_skips_file_checkout(self, monkeypatch, recording):
        result = _invoke(monkeypatch, branch="chore/462-x", checkout_type="0")
        assert result.exit_code == 0
        assert recording.started == []

    def test_no_issue_branch_does_nothing(self, monkeypatch, recording):
        result = _invoke(monkeypatch, branch="main", checkout_type="1")
        assert result.exit_code == 0
        assert recording.started == []

    def test_runs_when_checkout_type_unset(self, monkeypatch, recording):
        result = _invoke(monkeypatch, branch="feat/99-y", checkout_type=None)
        assert result.exit_code == 0
        assert recording.started == [99]

    def test_metrics_failure_is_non_fatal(self, monkeypatch, recording):
        def boom(self, issue_number=None):  # noqa: ARG001 - signature must match start_session
            raise RuntimeError("metrics store unavailable")

        del recording  # fixture used for its DogfoodingMetrics monkeypatch side effect
        monkeypatch.setattr(_RecordingMetrics, "start_session", boom)
        result = _invoke(monkeypatch, branch="fix/5-z", checkout_type="1")
        assert result.exit_code == 0

    def test_git_failure_is_non_fatal(self, monkeypatch, recording):
        def boom():
            raise OSError("git not found")

        monkeypatch.setattr(dm, "_current_branch", boom)
        monkeypatch.setenv("PRE_COMMIT_CHECKOUT_TYPE", "1")
        result = click.testing.CliRunner().invoke(dm.cli, ["start-on-checkout"])
        assert result.exit_code == 0
        assert recording.started == []


_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_SED = re.compile(r"sed -nE '[^']*'")


@pytest.mark.skipif(os.name == "nt", reason="the shell helpers are bash-only")
class TestShellIssueParsing:
    """The bash helpers parse branches exactly like ``_extract_issue`` (#576)."""

    @pytest.mark.parametrize("script", ["install_hooks.sh", "setup_aliases.sh"])
    @pytest.mark.parametrize(("branch", "expected"), _BRANCH_CASES)
    def test_shell_matches_python(self, script, branch, expected):
        commands = _SED.findall((_SCRIPTS / script).read_text(encoding="utf-8"))
        assert len(commands) == 1, f"{script}: expected one issue-parsing sed, got {commands}"
        out = subprocess.run(  # noqa: S603 - fixed command built from a repo script
            ["bash", "-c", f'printf "%s\\n" "$1" | {commands[0]}', "_", branch],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert (int(out) if out else None) == expected
