"""A nested git worktree must not contribute a second copy of the project (#507).

``.claude/worktrees/`` is this project's documented location for isolated
worktrees, and the project file scan used to recurse into it — giving every
project symbol a duplicate definition site from a sibling branch that may be
on a different commit, mid-edit, or deleting the very symbol being indexed.
"""

import pytest

from pyeye.analyzers import project_graph
from pyeye.analyzers.jedi_analyzer import JediAnalyzer

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
