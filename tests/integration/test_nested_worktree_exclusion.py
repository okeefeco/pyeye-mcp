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


@pytest.mark.skipif(shutil.which("git") is None, reason="requires a git executable")
class TestPluginScansUseTheSharedFilter:
    """#517: the plugins' whole-tree scans apply the same exclusion rule as ``rglob_async``.

    They called ``Path.rglob`` / ``Path.glob("**/…")`` directly, so they reported a
    second copy of every ``models.py`` / ``views.py`` from a nested worktree, and
    read ``.venv``. Built from real ``git`` output; submodules stay included.
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
    def project(self, tmp_path):
        library = tmp_path / "library"
        (library / "libapp").mkdir(parents=True)
        (library / "libapp" / "models.py").write_text("VALUE = 1\n")
        self._git("init", "-q", "-b", "main", ".", cwd=library)
        self._git("add", "-A", cwd=library)
        self._git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init", cwd=library)

        project = tmp_path / "project"
        (project / "blog" / "migrations").mkdir(parents=True)
        (project / "blog" / "templates").mkdir()
        (project / "blog" / "static").mkdir()
        for name in ("models.py", "views.py", "urls.py", "forms.py", "admin.py", "serializers.py"):
            (project / "blog" / name).write_text(
                "from pydantic import BaseModel\n@app.route('/')\nBlueprint\n"
            )
        (project / "blog" / "migrations" / "0001_initial.py").write_text("")
        self._git("init", "-q", "-b", "main", ".", cwd=project)
        self._git("add", "-A", cwd=project)
        self._git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init", cwd=project)
        self._git("submodule", "add", "-q", "../library", "vendor/library", cwd=project)
        self._git(
            "worktree", "add", "-q", ".claude/worktrees/feature", "-b", "feature", cwd=project
        )
        venv_app = project / ".venv" / "lib" / "site" / "blog"
        (venv_app / "migrations").mkdir(parents=True)
        (venv_app / "templates").mkdir()
        (venv_app / "models.py").write_text("from pydantic import BaseModel\n")
        (venv_app / "migrations" / "0001_initial.py").write_text("")
        return project

    @staticmethod
    def _rel(paths, root: Path) -> list[str]:
        return sorted(Path(p).relative_to(root).as_posix() for p in paths)

    def test_filtered_rglob_is_the_shared_rule(self, project):
        from pyeye.async_utils import filtered_rglob

        assert self._rel(filtered_rglob("models.py", project), project) == [
            "blog/models.py",
            "vendor/library/libapp/models.py",
        ]

    def test_django_components(self, project):
        from pyeye.plugins.django import DjangoPlugin

        components = DjangoPlugin(str(project)).get_framework_components()

        assert self._rel(components["models"], project) == [
            "blog/models.py",
            "vendor/library/libapp/models.py",
        ]
        for kind in ("views", "urls", "serializers", "admin", "forms"):
            assert self._rel(components[kind], project) == [f"blog/{kind}.py"], kind

    @pytest.mark.asyncio
    async def test_django_migrations(self, project):
        from pyeye.plugins.django import DjangoPlugin

        migrations = await DjangoPlugin(str(project)).find_migrations(scope="main")

        assert self._rel([m["file"] for m in migrations], project) == [
            "blog/migrations/0001_initial.py"
        ]

    def test_flask_components(self, project):
        from pyeye.plugins.flask import FlaskPlugin

        components = FlaskPlugin(str(project)).get_framework_components()

        assert self._rel(components["routes"], project) == self._rel(
            components["blueprints"], project
        )
        assert all(
            not p.startswith((".claude", ".venv")) for p in self._rel(components["routes"], project)
        )
        assert self._rel(components["models"], project) == [
            "blog/models.py",
            "vendor/library/libapp/models.py",
        ]
        assert self._rel(components["forms"], project) == ["blog/forms.py"]
        assert self._rel(components["templates"], project) == ["blog/templates"]
        assert self._rel(components["static"], project) == ["blog/static"]

    def test_pydantic_detection_ignores_worktrees_and_venv(self, project):
        from pyeye.plugins.pydantic import PydanticPlugin

        # Only the worktree and .venv import pydantic: detection must say no.
        for name in ("models.py", "views.py", "urls.py", "forms.py", "admin.py", "serializers.py"):
            (project / "blog" / name).write_text("VALUE = 1\n")

        assert PydanticPlugin(str(project)).detect() is False


#: Direct recursive scans that are deliberately NOT whole-tree project scans.
_SUBTREE_SCANS = {
    # ``.venv/lib`` is searched FOR site-packages, inside the excluded dir on purpose.
    ("config.py", 'venv_path.rglob("site-packages")'),
    # A templates directory one level below a root, found by a non-recursive glob.
    ("django.py", 'template_dir.rglob("*.html")'),
    ("flask.py", 'template_dir.rglob("*.html")'),
    ("flask.py", 'template_dir.rglob("*.jinja2")'),
    # The rule's own home.
    ("async_utils.py", "path.rglob(pattern)"),
}


def test_every_whole_tree_scan_goes_through_filtered_rglob():
    """#517: the exclusion rule has one home; no project scan bypasses it."""
    import re

    src = Path(__file__).resolve().parents[2] / "src" / "pyeye"
    found = set()
    for py in src.rglob("*.py"):
        for line in py.read_text(encoding="utf-8").splitlines():
            for call in re.findall(r"[\w.]+\.(?:rglob\([^)]*\)|glob\(\"\*\*[^)]*\))", line):
                found.add((py.name, call))
    assert found <= _SUBTREE_SCANS, sorted(found - _SUBTREE_SCANS)
