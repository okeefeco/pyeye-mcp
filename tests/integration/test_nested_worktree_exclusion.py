"""A nested git worktree must not contribute a second copy of the project (#507).

``.claude/worktrees/`` is this project's documented location for isolated
worktrees, and the project file scan used to recurse into it — giving every
project symbol a duplicate definition site from a sibling branch that may be
on a different commit, mid-edit, or deleting the very symbol being indexed.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from pyeye.analyzers import project_graph
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.async_utils import rglob_async

WORKTREE_GITDIR = "gitdir: /elsewhere/.git/worktrees/feature\n"


@pytest.fixture
def project_with_nested_worktree(tmp_path):
    """A project whose ``.claude/worktrees/`` holds a full duplicate checkout."""
    package = tmp_path / "src" / "app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "models.py").write_text("class StatusTracker:\n    pass\n")

    worktree = tmp_path / ".claude" / "worktrees" / "feature"
    duplicate = worktree / "src" / "app"
    duplicate.mkdir(parents=True)
    (worktree / ".git").write_text(WORKTREE_GITDIR)
    (duplicate / "__init__.py").write_text("")
    # The sibling branch is mid-edit: same symbol, shifted to a different line.
    (duplicate / "models.py").write_text("\n\nclass StatusTracker:\n    pass\n")

    project_graph.invalidate()
    return tmp_path


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["main", "all"])
async def test_worktree_files_never_enter_the_project_scan(project_with_nested_worktree, scope):
    """Acceptance criterion 1: no scope reaches into the nested checkout."""
    analyzer = JediAnalyzer(str(project_with_nested_worktree))

    files = await analyzer.get_project_files(pattern="*.py", scope=scope)

    assert [f for f in files if ".claude" in f.parts] == []


@pytest.mark.asyncio
async def test_symbol_has_exactly_one_definition_site(project_with_nested_worktree):
    """Acceptance criterion 2: one definition per symbol, worktree present."""
    analyzer = JediAnalyzer(str(project_with_nested_worktree))

    definitions = await analyzer._search_all_scopes("StatusTracker", scope="all")

    assert len(definitions) == 1
    assert ".claude" not in definitions[0].module_path.parts


@pytest.mark.skipif(shutil.which("git") is None, reason="requires a git executable")
class TestAgainstRealGitLayouts:
    """Guard the rule against what ``git`` actually writes on disk.

    Every other test here fabricates the on-disk layout, so a fixture that
    drifts from git's real output makes the whole suite agree with itself and
    with nothing else — which is how the first cut of this fix shipped a
    submodule guard that fabricated a ``.git`` *directory*, a layout git has
    not produced since 1.7.8. These tests build the layouts with git itself.
    """

    @staticmethod
    def _git(*args: str, cwd: Path) -> None:
        subprocess.run(
            ["git", "-c", "protocol.file.allow=always", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
        )

    @pytest.fixture
    def repo_with_worktree_and_submodule(self, tmp_path):
        """A real repo carrying both a linked worktree and a submodule."""
        library = tmp_path / "library"
        library.mkdir()
        self._git("init", "-q", "-b", "main", ".", cwd=library)
        (library / "lib.py").write_text("VALUE = 1\n")
        self._git("add", "-A", cwd=library)
        self._git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init", cwd=library)

        project = tmp_path / "project"
        project.mkdir()
        self._git("init", "-q", "-b", "main", ".", cwd=project)
        (project / "app.py").write_text("VALUE = 2\n")
        self._git("add", "-A", cwd=project)
        self._git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init", cwd=project)
        self._git("submodule", "add", "-q", "../library", "vendor/library", cwd=project)
        self._git(
            "worktree", "add", "-q", ".claude/worktrees/feature", "-b", "feature", cwd=project
        )
        return project

    @pytest.mark.asyncio
    async def test_real_worktree_is_excluded_and_real_submodule_is_kept(
        self, repo_with_worktree_and_submodule
    ):
        project = repo_with_worktree_and_submodule
        # Precondition: git gives both a ``.git`` *file*, so the two are only
        # distinguishable by what that pointer points at.
        assert (project / ".claude" / "worktrees" / "feature" / ".git").is_file()
        assert (project / "vendor" / "library" / ".git").is_file()

        results = await rglob_async("*.py", project)

        assert sorted(p.relative_to(project).as_posix() for p in results) == [
            "app.py",
            "vendor/library/lib.py",
        ]
