"""Tests for the ``start-on-checkout`` metrics command (#462).

This command is wired as a pre-commit ``post-checkout`` hook so that switching
to an issue-numbered branch auto-starts a dogfooding metrics session. It
replaces the old, uncommitted ``.git/hooks/post-checkout`` that only ran on one
developer's machine and shelled out with a bare ``python`` interpreter.
"""

from __future__ import annotations

import click.testing
import pytest

import scripts.dogfooding_metrics as dm


class TestExtractIssue:
    """Branch-name → issue-number parsing (first run of digits, like the old hook)."""

    @pytest.mark.parametrize(
        ("branch", "expected"),
        [
            ("chore/462-pre-commit-managed-hooks", 462),
            ("feat/23-add-validation", 23),
            ("fix/7", 7),
            ("main", None),
            ("develop", None),
            ("", None),
        ],
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
