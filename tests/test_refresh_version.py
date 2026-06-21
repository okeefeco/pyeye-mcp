"""Tests for scripts/refresh_version.py (the setuptools_scm version-file refresher).

Wired as a pre-commit ``post-merge`` / ``post-checkout`` hook (#462) so the
``setuptools_scm``-generated ``src/pyeye/_version.py`` is refreshed after the
working tree's git state changes (a plain ``git pull`` or branch checkout),
instead of drifting until the next install.
"""

from __future__ import annotations

from scripts.refresh_version import main, should_run


class TestShouldRun:
    """The post-checkout file-vs-branch guard via PRE_COMMIT_CHECKOUT_TYPE."""

    def test_skips_file_checkout(self, monkeypatch):
        """A file checkout (pre-commit exports CHECKOUT_TYPE='0') must not regen."""
        monkeypatch.setenv("PRE_COMMIT_CHECKOUT_TYPE", "0")
        assert should_run() is False

    def test_runs_on_branch_checkout(self, monkeypatch):
        """A branch checkout (CHECKOUT_TYPE='1') should regen."""
        monkeypatch.setenv("PRE_COMMIT_CHECKOUT_TYPE", "1")
        assert should_run() is True

    def test_runs_when_unset(self, monkeypatch):
        """post-merge sets no checkout type → still regen (default-on)."""
        monkeypatch.delenv("PRE_COMMIT_CHECKOUT_TYPE", raising=False)
        assert should_run() is True


class TestMain:
    """main() drives the regen subprocess, guarded and failure-tolerant."""

    def test_invokes_setuptools_scm_when_running(self, monkeypatch):
        """When the guard allows it, main() force-writes the version file."""
        monkeypatch.delenv("PRE_COMMIT_CHECKOUT_TYPE", raising=False)
        calls = []
        monkeypatch.setattr(
            "scripts.refresh_version.subprocess.run",
            lambda *a, **k: calls.append((a, k)),
        )

        assert main() == 0
        assert len(calls) == 1
        argv = calls[0][0][0]
        assert argv[1:] == ["-m", "setuptools_scm", "--force-write-version-files"]

    def test_does_not_invoke_on_file_checkout(self, monkeypatch):
        """When guarded out, main() must not shell out at all."""
        monkeypatch.setenv("PRE_COMMIT_CHECKOUT_TYPE", "0")
        calls = []
        monkeypatch.setattr(
            "scripts.refresh_version.subprocess.run",
            lambda *a, **k: calls.append((a, k)),
        )

        assert main() == 0
        assert calls == []

    def test_swallows_subprocess_failure(self, monkeypatch):
        """A regen failure never blocks the pull/checkout (always exit 0)."""
        monkeypatch.delenv("PRE_COMMIT_CHECKOUT_TYPE", raising=False)

        def boom(*_args, **_kwargs):
            raise OSError("setuptools_scm exploded")

        monkeypatch.setattr("scripts.refresh_version.subprocess.run", boom)

        assert main() == 0
