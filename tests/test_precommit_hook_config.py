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


def _runs_at(hook, config, stage):
    """Whether *hook* runs at *stage*, mirroring pre-commit's resolution.

    A hook with explicit ``stages`` runs only in those. A hook WITHOUT ``stages``
    falls back to the top-level ``default_stages``; when that is absent too,
    pre-commit runs the hook in *every* installed stage (the #477 footgun).
    """
    if "stages" in hook:
        return stage in hook["stages"]
    default = config.get("default_stages")
    return default is None or stage in default


def _hooks_at(config, stage):
    return {
        hook["id"]
        for repo in config["repos"]
        for hook in repo["hooks"]
        if _runs_at(hook, config, stage)
    }


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


def test_only_intended_hooks_run_on_checkout_and_merge():
    """Unscoped lint/format/conformance hooks must NOT fire on checkout/merge (#477).

    Adding post-merge/post-checkout to ``default_install_hook_types`` (#462) made
    every hook lacking explicit ``stages`` also run on those git events — notably
    the ``always_run`` ``conformance-linter`` (a multi-second pytest run) on every
    ``git checkout``/``git pull``. A top-level ``default_stages: [pre-commit]``
    scopes the unscoped hooks back to commit time; only the two hooks that
    explicitly opt into the git-state stages should fire there.
    """
    config = _load()
    assert _hooks_at(config, "post-checkout") == {
        "refresh-version-file",
        "start-metrics-session",
    }
    assert _hooks_at(config, "post-merge") == {"refresh-version-file"}


def test_all_uv_run_entries_are_frozen():
    """No hook may invoke a bare ``uv run`` — it must be ``uv run --frozen`` (#479).

    Bare ``uv run`` can re-resolve and rewrite ``uv.lock`` as a side effect
    (notably behind a PyPI mirror), which trips pre-commit's framework-level
    "files were modified by this hook" check and fails the hook — independent of
    the script's own exit code. ``--frozen`` pins the lock so the hooks run the
    tools without ever mutating it.
    """
    offenders = []
    for repo in _load()["repos"]:
        for hook in repo["hooks"]:
            entry = hook.get("entry", "")
            if "uv run" in entry and "uv run --frozen" not in entry:
                offenders.append(hook["id"])
    assert (
        not offenders
    ), f"hooks using a bare 'uv run' (must be 'uv run --frozen', #479): {offenders}"


def test_default_stages_scopes_unscoped_hooks_to_commit():
    """The conformance-linter (unscoped, always_run) must resolve to commit-only."""
    config = _load()
    assert config.get("default_stages") == ["pre-commit"]
    assert _runs_at(_hook(config, "conformance-linter"), config, "post-checkout") is False
    assert _runs_at(_hook(config, "conformance-linter"), config, "pre-commit") is True


def test_hook_python_is_not_pinned_to_a_minor_version():
    """Hook envs must build with the running interpreter, not a fixed minor (#529).

    ``default_language_version: python: python3.12`` broke CI the moment the
    pre-commit job moved to Python 3.13: the runner had no ``python3.12``, so
    virtualenv could not build the detect-secrets hook env. Any minor pin
    re-breaks on the next interpreter bump (3.14, #543).
    """
    config = _load()
    pins = [("default_language_version", config.get("default_language_version", {}).get("python"))]
    pins += [
        (hook["id"], hook.get("language_version"))
        for repo in config["repos"]
        for hook in repo["hooks"]
    ]
    pinned = [(where, v) for where, v in pins if v and v not in ("python3", "python", "default")]
    assert not pinned, f"hook Python pinned to a specific version: {pinned}"


# Remote repos allowed to stay remote: non-Python hooks only, which uv can't run.
_ALLOWED_REMOTE_REPOS = {"https://github.com/igorshubovych/markdownlint-cli"}

# Python tool hooks that must run from the uv-managed venv (#413, #547).
_UV_RUN_HOOKS = {
    "detect-secrets",
    "bandit",
    "pydocstyle",
    "commitizen",
    "trailing-whitespace",
    "end-of-file-fixer",
    "check-yaml",
    "check-toml",
    "check-added-large-files",
    "check-case-conflict",
    "check-merge-conflict",
    "check-docstring-first",
    "debug-statements",
    "detect-private-key",
    "mixed-line-ending",
    "name-tests-test",
    "check-json",
    "pretty-format-json",
}


def test_only_non_python_hooks_use_remote_repos():
    """Python hooks run via ``uv run`` so their versions come from uv.lock (#547).

    A remote repo pins its own tool version (``rev:``) in a separate env, which
    drifted from the lock (bandit 1.8.6 vs 1.9.4, commitizen 3.13.0 vs 4.19.3)
    and depended on ``default_language_version`` (#529).
    """
    remote = {repo["repo"] for repo in _load()["repos"] if repo["repo"] != "local"}
    unexpected = remote - _ALLOWED_REMOTE_REPOS
    assert not unexpected, f"unexpected remote hook repos: {unexpected}"


def test_python_tool_hooks_run_through_uv():
    config = _load()
    for hook_id in sorted(_UV_RUN_HOOKS):
        entry = _hook(config, hook_id).get("entry", "")
        assert entry.startswith("uv run --frozen "), f"{hook_id}: entry {entry!r}"
