"""Tests for the WorktreeCreate hook (worktree_create.py).

These are characterization/backfill tests for a hook that already existed
untested. Every expectation is derived from the *documented contract* — the
function docstrings, the ``worktree_create.yaml`` comments, and the README
naming table — not from reading the implementation, so a failure signals a real
discrepancy rather than merely encoding current behaviour.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess
from types import ModuleType

import pytest

# A minimal prefix map matching the bundled config's canonical/alias scheme,
# used to unit-test parse_name in isolation from config loading.
PREFIX_MAP = {
    "feat": "feat",
    "feature": "feat",
    "fix": "fix",
    "bugfix": "fix",
    "docs": "docs",
}


# ---------------------------------------------------------------------------
# parse_name — the nested naming model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("feat-361-desc", "feat/361-desc"),  # flat dash form normalised to nested
        ("feature/361-desc", "feat/361-desc"),  # alias collapsed (slash form)
        ("feat/361-desc", "feat/361-desc"),  # already canonical, unchanged
        ("bugfix-7-x", "fix/7-x"),  # alias -> canonical
        ("docs-1-readme", "docs/1-readme"),
    ],
)
def test_parse_name_normalises_recognised_prefix(wtc: ModuleType, name: str, expected: str) -> None:
    """A recognised prefix is normalised and the name becomes a nested path."""
    branch, directory = wtc.parse_name(name, PREFIX_MAP)
    # Branch and directory always share the same nested form.
    assert branch == expected
    assert directory == expected


@pytest.mark.parametrize("name", ["random-thing", "scratch", "wip/123-x"])
def test_parse_name_passes_through_unrecognised(wtc: ModuleType, name: str) -> None:
    """An unrecognised prefix (or no separator) passes through verbatim."""
    assert wtc.parse_name(name, PREFIX_MAP) == (name, name)


def test_parse_name_flat_and_slash_forms_collapse_identically(wtc: ModuleType) -> None:
    """Normalisation fires the same way for the dash and slash forms."""
    assert wtc.parse_name("bugfix-7-x", PREFIX_MAP) == wtc.parse_name("bugfix/7-x", PREFIX_MAP)


# ---------------------------------------------------------------------------
# build_prefix_map
# ---------------------------------------------------------------------------


def test_build_prefix_map_maps_canonicals_and_aliases(wtc: ModuleType) -> None:
    """Every canonical maps to itself and each alias maps to its canonical."""
    config = {
        "branch_types": [
            {"canonical": "fix", "aliases": ["bugfix", "bug"]},
            {"canonical": "feat", "aliases": ["feature"]},
        ]
    }
    assert wtc.build_prefix_map(config) == {
        "fix": "fix",
        "bugfix": "fix",
        "bug": "fix",
        "feat": "feat",
        "feature": "feat",
    }


def test_build_prefix_map_skips_entries_without_canonical(wtc: ModuleType) -> None:
    """An entry missing a canonical is ignored rather than crashing."""
    config = {"branch_types": [{"aliases": ["x"]}, {"canonical": "feat"}]}
    assert wtc.build_prefix_map(config) == {"feat": "feat"}


# ---------------------------------------------------------------------------
# resolve_work_base — worktree location layouts
# ---------------------------------------------------------------------------


def test_resolve_work_base_native(wtc: ModuleType, tmp_path: Path) -> None:
    """native -> <repo>/.claude/worktrees/ with an info/exclude entry."""
    base, exclude = wtc.resolve_work_base(tmp_path, {"worktree_location": "native"})
    assert base == tmp_path / ".claude" / "worktrees"
    assert exclude == ".claude/worktrees/"


def test_resolve_work_base_in_repo(wtc: ModuleType, tmp_path: Path) -> None:
    """in-repo -> <repo>/<in_repo_dir>/ with a matching exclude entry."""
    base, exclude = wtc.resolve_work_base(
        tmp_path, {"worktree_location": "in-repo", "in_repo_dir": ".worktrees"}
    )
    assert base == tmp_path / ".worktrees"
    assert exclude == ".worktrees/"


def test_resolve_work_base_sibling(wtc: ModuleType, tmp_path: Path) -> None:
    """sibling -> <repo-parent>/<repo><suffix>/ and needs no exclude."""
    repo = tmp_path / "myrepo"
    base, exclude = wtc.resolve_work_base(
        repo, {"worktree_location": "sibling", "work_dir_suffix": "-wtree"}
    )
    assert base == tmp_path / "myrepo-wtree"
    assert exclude is None


def test_resolve_work_base_unknown_falls_back_to_native(wtc: ModuleType, tmp_path: Path) -> None:
    """An unknown location defaults to the native layout."""
    base, exclude = wtc.resolve_work_base(tmp_path, {"worktree_location": "bogus"})
    assert base == tmp_path / ".claude" / "worktrees"
    assert exclude == ".claude/worktrees/"


# ---------------------------------------------------------------------------
# load_config — bundled defaults + project overrides
# ---------------------------------------------------------------------------


def test_load_config_bundled_defaults(wtc: ModuleType, repo: Path) -> None:
    """With no project config, the bundled defaults load and parse."""
    config = wtc.load_config(repo)
    assert config["worktree_location"] == "native"
    assert config["branch_types"]  # non-empty
    prefix_map = wtc.build_prefix_map(config)
    # Aliases from the bundled yaml collapse to their canonicals.
    assert prefix_map["feature"] == "feat"
    assert prefix_map["bugfix"] == "fix"


def test_load_config_project_override_wins(wtc: ModuleType, repo: Path) -> None:
    """A project .claude/hooks/worktree_create.yaml overrides bundled scalars."""
    project_cfg = repo / ".claude" / "hooks" / "worktree_create.yaml"
    project_cfg.parent.mkdir(parents=True, exist_ok=True)
    project_cfg.write_text("worktree_location: in-repo\n")

    config = wtc.load_config(repo)
    assert config["worktree_location"] == "in-repo"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def test_get_default_branch_local_main(wtc: ModuleType, repo: Path) -> None:
    """With no remote, the default branch is the local main."""
    assert wtc.get_default_branch(repo) == "main"


def test_branch_exists_local(wtc: ModuleType, repo: Path) -> None:
    """It distinguishes existing from non-existent local branches."""
    assert wtc.branch_exists_local(repo, "main") is True
    assert wtc.branch_exists_local(repo, "no-such-branch") is False


def test_find_worktree_for_branch(
    wtc: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """It locates the worktree that has a given branch checked out."""
    worktree = tmp_path / "wt"
    run_git(repo, "worktree", "add", "-b", "feat/x", str(worktree))

    found = wtc.find_worktree_for_branch(repo, "feat/x")
    assert found is not None
    assert found.resolve() == worktree.resolve()
    assert wtc.find_worktree_for_branch(repo, "feat/absent") is None


def test_find_main_repo_root_from_inside_worktree(
    wtc: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """Called from within a worktree, it resolves back to the main repo."""
    worktree = tmp_path / "wt"
    run_git(repo, "worktree", "add", "-b", "feat/inside", str(worktree))

    resolved = wtc.find_main_repo_root(str(worktree))
    assert resolved is not None
    assert resolved.resolve() == repo.resolve()


# ---------------------------------------------------------------------------
# main — end-to-end worktree creation
# ---------------------------------------------------------------------------


def test_main_creates_nested_worktree(
    wtc: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() creates the worktree at the nested path and prints it on stdout."""
    payload = {
        "hook_event_name": "WorktreeCreate",
        "name": "feat-900-thing",
        "cwd": str(repo),
        "session_id": "s",
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(wtc, "setup_logging", lambda: None)  # keep tests hermetic

    rc = wtc.main()

    assert rc == 0
    printed = capsys.readouterr().out.strip()
    expected = repo / ".claude" / "worktrees" / "feat" / "900-thing"
    assert Path(printed).resolve() == expected.resolve()
    assert expected.is_dir()
    # The branch was created in canonical nested form.
    found = wtc.find_worktree_for_branch(repo, "feat/900-thing")
    assert found is not None and found.resolve() == expected.resolve()


def test_main_reentrant_returns_existing_worktree(
    wtc: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Re-entering an existing branch returns its worktree instead of erroring."""
    payload = {
        "hook_event_name": "WorktreeCreate",
        "name": "feat-900-thing",
        "cwd": str(repo),
        "session_id": "s",
    }

    def _run() -> tuple[int, str]:
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        monkeypatch.setattr(wtc, "setup_logging", lambda: None)
        code = wtc.main()
        return code, capsys.readouterr().out.strip()

    rc1, path1 = _run()
    rc2, path2 = _run()

    assert rc1 == 0 and rc2 == 0
    assert path1 == path2  # same worktree returned, no error on re-entry
