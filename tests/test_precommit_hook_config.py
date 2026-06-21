"""Contract tests for the git-state hooks wired into .pre-commit-config.yaml (#462).

These guard the two hooks that must stay pre-commit-managed (so every
contributor gets them, not just one developer's local .git/hooks):

* ``refresh-version-file`` — regen setuptools_scm version on pull/merge/checkout
* ``start-metrics-session`` — start a dogfooding session on issue-branch checkout

The contract that matters is *which stages they run on* and that pre-commit is
configured to install those stage hook types.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_CONFIG = Path(__file__).resolve().parents[1] / ".pre-commit-config.yaml"


def _load():
    return yaml.safe_load(_CONFIG.read_text(encoding="utf-8"))


def _hook(config, hook_id):
    for repo in config["repos"]:
        for hook in repo["hooks"]:
            if hook["id"] == hook_id:
                return hook
    raise AssertionError(f"hook {hook_id!r} not found in .pre-commit-config.yaml")


def test_install_types_include_checkout_and_merge():
    """A bare `pre-commit install` must wire post-merge and post-checkout."""
    install_types = _load()["default_install_hook_types"]
    assert "post-merge" in install_types
    assert "post-checkout" in install_types


def test_refresh_version_runs_on_merge_and_checkout():
    hook = _hook(_load(), "refresh-version-file")
    assert set(hook["stages"]) == {"post-merge", "post-checkout"}
    assert hook["pass_filenames"] is False


def test_metrics_session_runs_on_checkout_only():
    hook = _hook(_load(), "start-metrics-session")
    assert hook["stages"] == ["post-checkout"]
    assert hook["pass_filenames"] is False
