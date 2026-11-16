"""Comprehensive tests for async_utils module."""

import os
from pathlib import Path

import pytest

from pyeye.async_utils import (
    read_file_async,
    rglob_async,
)


@pytest.mark.asyncio
class TestReadFileAsync:
    """Test read_file_async function."""

    async def test_read_file_basic(self, tmp_path):
        """Test reading a basic file."""
        test_file = tmp_path / "test.txt"
        test_content = "Hello, World!"
        test_file.write_text(test_content)

        content = await read_file_async(test_file)
        assert content == test_content

    async def test_read_file_unicode(self, tmp_path):
        """Test reading a file with Unicode content."""
        test_file = tmp_path / "unicode.txt"
        test_content = "Hello, 世界! 🌍"
        test_file.write_text(test_content, encoding="utf-8")

        content = await read_file_async(test_file)
        assert content == test_content

    async def test_read_file_multiline(self, tmp_path):
        """Test reading a multiline file."""
        test_file = tmp_path / "multiline.txt"
        test_content = "Line 1\nLine 2\nLine 3"
        test_file.write_text(test_content)

        content = await read_file_async(test_file)
        assert content == test_content

    async def test_read_file_not_found(self):
        """Test reading a non-existent file."""
        non_existent = Path("/tmp/does_not_exist_12345.txt")

        with pytest.raises(FileNotFoundError):
            await read_file_async(non_existent)

    @pytest.mark.skipif(os.name == "nt", reason="Windows handles permissions differently")
    async def test_read_file_permission_error(self, tmp_path):
        """Test reading a file without permissions."""
        test_file = tmp_path / "no_read.txt"
        test_file.write_text("secret")
        test_file.chmod(0o000)

        try:
            with pytest.raises(OSError):
                await read_file_async(test_file)
        finally:
            # Restore permissions for cleanup
            test_file.chmod(0o644)

    async def test_read_file_empty(self, tmp_path):
        """Test reading an empty file."""
        test_file = tmp_path / "empty.txt"
        test_file.write_text("")

        content = await read_file_async(test_file)
        assert content == ""

    async def test_read_file_large(self, tmp_path):
        """Test reading a large file."""
        test_file = tmp_path / "large.txt"
        test_content = "x" * 100000  # 100KB of data
        test_file.write_text(test_content)

        content = await read_file_async(test_file)
        assert content == test_content
        assert len(content) == 100000


@pytest.mark.asyncio
class TestRglobAsync:
    """Test rglob_async function."""

    async def test_rglob_recursive(self, tmp_path):
        """Test recursive glob pattern."""
        # Create nested structure
        (tmp_path / "test1.py").write_text("")
        subdir1 = tmp_path / "subdir1"
        subdir1.mkdir()
        (subdir1 / "test2.py").write_text("")
        subdir2 = subdir1 / "subdir2"
        subdir2.mkdir()
        (subdir2 / "test3.py").write_text("")

        results = await rglob_async("*.py", tmp_path)

        assert len(results) == 3
        assert all(p.suffix == ".py" for p in results)

    async def test_rglob_no_matches(self, tmp_path):
        """Test recursive glob with no matches."""
        results = await rglob_async("*.xyz", tmp_path)
        assert results == []

    async def test_rglob_directory_pattern(self, tmp_path):
        """Test recursive glob matching directories."""
        # Create nested test directories
        (tmp_path / "test_dir").mkdir()
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "test_dir").mkdir()

        results = await rglob_async("test_*", tmp_path)

        assert len(results) == 2

    async def test_rglob_all_files(self, tmp_path):
        """Test recursive glob for all files."""
        # Create nested files
        (tmp_path / "file1.txt").write_text("")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file2.txt").write_text("")

        results = await rglob_async("*.txt", tmp_path)

        assert len(results) == 2


@pytest.mark.asyncio
class TestRglobAsyncNestedCheckouts:
    """Nested git worktrees must not be scanned (#507).

    A linked worktree is by definition a duplicate of the parent tree, so
    scanning one gives every project symbol a second definition site --
    possibly on another branch, or mid-edit.
    """

    @staticmethod
    def _make_worktree(parent: Path, name: str) -> Path:
        """Create a directory that looks like a linked git worktree.

        A linked worktree's ``.git`` is a *file* holding a gitdir pointer,
        unlike a normal clone where it is a directory.
        """
        worktree = parent / name
        worktree.mkdir(parents=True)
        (worktree / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n")
        return worktree

    async def test_excludes_files_inside_a_nested_worktree(self, tmp_path):
        """Files under a linked worktree are not returned."""
        (tmp_path / "real.py").write_text("")
        worktree = self._make_worktree(tmp_path, "some-worktree")
        (worktree / "duplicate.py").write_text("")

        results = await rglob_async("*.py", tmp_path)

        assert [p.name for p in results] == ["real.py"]

    async def test_excludes_worktree_under_dot_claude_worktrees(self, tmp_path):
        """The reported layout: worktrees live under .claude/worktrees/."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("")
        worktree = self._make_worktree(tmp_path / ".claude" / "worktrees" / "fix", "507")
        (worktree / "src").mkdir()
        (worktree / "src" / "app.py").write_text("")

        results = await rglob_async("*.py", tmp_path)

        assert [p.relative_to(tmp_path).as_posix() for p in results] == ["src/app.py"]

    async def test_excludes_deeply_nested_files_in_a_worktree(self, tmp_path):
        """Exclusion applies at any depth below the worktree root."""
        worktree = self._make_worktree(tmp_path, "wt")
        deep = worktree / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "buried.py").write_text("")

        results = await rglob_async("*.py", tmp_path)

        assert results == []

    async def test_includes_files_in_a_submodule(self, tmp_path):
        """Regression guard for the chosen rule: submodules stay indexed.

        Since git 1.7.8 a submodule's ``.git`` is a *file* too, pointing at
        ``<super>/.git/modules/<name>`` — so "``.git`` is a file" alone does
        not mean "linked worktree". Submodule source is often genuinely
        imported by the parent project, so it must NOT be treated as a nested
        checkout. The fixture mirrors what ``git submodule add`` writes.
        """
        submodule = tmp_path / "vendor" / "shared-lib"
        submodule.mkdir(parents=True)
        (submodule / ".git").write_text("gitdir: ../../.git/modules/vendor/shared-lib\n")
        gitdir = tmp_path / ".git" / "modules" / "vendor" / "shared-lib"
        gitdir.mkdir(parents=True)
        # A submodule gitdir is a full repository: no ``commondir`` back-pointer.
        (gitdir / "HEAD").write_text("ref: refs/heads/main\n")
        (gitdir / "config").write_text("")
        (submodule / "lib.py").write_text("")

        results = await rglob_async("*.py", tmp_path)

        assert [p.name for p in results] == ["lib.py"]

    async def test_includes_a_submodule_whose_path_is_named_worktrees(self, tmp_path):
        """The rule reads git's structure, not a ``worktrees`` path segment.

        A submodule checked out at ``worktrees/lib`` has the gitdir
        ``.git/modules/worktrees/lib`` — a path that *contains* a
        ``worktrees`` component. Guards against distinguishing the two kinds
        of pointer by path shape alone.
        """
        submodule = tmp_path / "worktrees" / "lib"
        submodule.mkdir(parents=True)
        (submodule / ".git").write_text("gitdir: ../../.git/modules/worktrees/lib\n")
        gitdir = tmp_path / ".git" / "modules" / "worktrees" / "lib"
        gitdir.mkdir(parents=True)
        (gitdir / "HEAD").write_text("ref: refs/heads/main\n")
        (submodule / "lib.py").write_text("")

        results = await rglob_async("*.py", tmp_path)

        assert [p.name for p in results] == ["lib.py"]

    async def test_excludes_a_worktree_with_a_live_gitdir(self, tmp_path):
        """A resolvable worktree pointer is confirmed via git's ``commondir``."""
        worktree = tmp_path / "wt"
        worktree.mkdir()
        (worktree / ".git").write_text("gitdir: ../.git/worktrees/wt\n")
        gitdir = tmp_path / ".git" / "worktrees" / "wt"
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_text("../..\n")
        (worktree / "duplicate.py").write_text("")
        (tmp_path / "real.py").write_text("")

        results = await rglob_async("*.py", tmp_path)

        assert [p.name for p in results] == ["real.py"]

    async def test_excludes_a_worktree_whose_gitdir_was_pruned(self, tmp_path):
        """A dangling worktree pointer still marks a duplicate checkout.

        ``git worktree prune`` deletes ``.git/worktrees/<name>`` but leaves the
        checkout on disk — still a full second copy of the tree, so the layout
        of the pointer is used when the target is gone.
        """
        worktree = tmp_path / "stale"
        worktree.mkdir()
        (worktree / ".git").write_text("gitdir: /gone/.git/worktrees/stale\n")
        (worktree / "duplicate.py").write_text("")

        results = await rglob_async("*.py", tmp_path)

        assert results == []

    async def test_includes_files_beside_an_unreadable_dot_git_file(self, tmp_path):
        """A ``.git`` file that is not a gitdir pointer is not a worktree."""
        odd = tmp_path / "odd"
        odd.mkdir()
        (odd / ".git").write_text("not a pointer\n")
        (odd / "app.py").write_text("")

        results = await rglob_async("*.py", tmp_path)

        assert [p.name for p in results] == ["app.py"]

    async def test_scanning_from_inside_a_worktree_still_returns_files(self, tmp_path):
        """The scan root itself is never treated as a nested checkout.

        Worktrees are this project's documented workflow, so pointing pyeye at
        one must behave normally. Guards the rule against over-reaching into
        "a worktree is never scannable".
        """
        (tmp_path / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n")
        (tmp_path / "app.py").write_text("")

        results = await rglob_async("*.py", tmp_path)

        assert [p.name for p in results] == ["app.py"]


class TestRglobNestedIndependentRepos:
    """A nested independent clone is another project, not this one's source (#810).

    Its ``.git`` is a directory. #507 named this "vendored nested clone" as known
    residue; the pyeye-scenarios convention (clones under ``.scenario-repos/``)
    then put 2,922 django files into pyeye-on-pyeye analysis.
    """

    @staticmethod
    def _make_clone(parent: Path, name: str) -> Path:
        clone = parent / name
        (clone / ".git").mkdir(parents=True)
        (clone / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        return clone

    async def test_excludes_a_nested_clone(self, tmp_path):
        (tmp_path / "app.py").write_text("")
        clone = self._make_clone(tmp_path / ".scenario-repos", "django")
        (clone / "django").mkdir()
        (clone / "django" / "base.py").write_text("")

        results = await rglob_async("*.py", tmp_path)

        assert [p.relative_to(tmp_path).as_posix() for p in results] == ["app.py"]

    async def test_excludes_a_clone_at_any_depth(self, tmp_path):
        clone = self._make_clone(tmp_path / "a" / "b", "vendored")
        (clone / "lib.py").write_text("")
        (tmp_path / "a" / "kept.py").write_text("")

        results = await rglob_async("*.py", tmp_path)

        assert [p.relative_to(tmp_path).as_posix() for p in results] == ["a/kept.py"]

    async def test_includes_a_plain_subdirectory(self, tmp_path):
        """A directory without ``.git`` is ordinary project source."""
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "mod.py").write_text("")

        results = await rglob_async("*.py", tmp_path)

        assert [p.relative_to(tmp_path).as_posix() for p in results] == ["pkg/mod.py"]

    async def test_the_scan_root_may_itself_be_a_clone(self, tmp_path):
        """The root is never tested: a project is normally a clone."""
        project = self._make_clone(tmp_path, "project")
        (project / "app.py").write_text("")

        results = await rglob_async("*.py", project)

        assert [p.name for p in results] == ["app.py"]

    async def test_keeps_an_old_style_submodule_declared_in_gitmodules(self, tmp_path):
        """A pre-1.7.8 submodule has a ``.git`` directory; ``.gitmodules`` keeps it."""
        (tmp_path / ".gitmodules").write_text(
            '[submodule "vendor/lib"]\n\tpath = vendor/lib\n\turl = ../lib\n'
        )
        submodule = self._make_clone(tmp_path / "vendor", "lib")
        (submodule / "lib.py").write_text("")
        other = self._make_clone(tmp_path / "vendor", "undeclared")
        (other / "noise.py").write_text("")

        results = await rglob_async("*.py", tmp_path)

        assert [p.relative_to(tmp_path).as_posix() for p in results] == ["vendor/lib/lib.py"]

    async def test_a_quoted_gitmodules_path_is_unquoted(self, tmp_path):
        (tmp_path / ".gitmodules").write_text('[submodule "x"]\n\tpath = "my lib"\n')
        submodule = self._make_clone(tmp_path, "my lib")
        (submodule / "lib.py").write_text("")

        results = await rglob_async("*.py", tmp_path)

        assert [p.name for p in results] == ["lib.py"]

    async def test_a_superprojects_gitmodules_above_the_root_counts(self, tmp_path):
        """Scanning a subdirectory of a superproject still honours its ``.gitmodules``."""
        (tmp_path / ".gitmodules").write_text('[submodule "s"]\n\tpath = proj/vendor/lib\n')
        project = tmp_path / "proj"
        submodule = self._make_clone(project / "vendor", "lib")
        (submodule / "lib.py").write_text("")

        results = await rglob_async("*.py", project)

        assert [p.relative_to(project).as_posix() for p in results] == ["vendor/lib/lib.py"]

    async def test_a_nested_superprojects_gitmodules_counts(self, tmp_path):
        """A ``.gitmodules`` met during the walk declares paths relative to its own directory."""
        sub = tmp_path / "tools"
        sub.mkdir()
        (sub / ".gitmodules").write_text('[submodule "s"]\n\tpath = third_party/lib\n')
        submodule = self._make_clone(sub / "third_party", "lib")
        (submodule / "lib.py").write_text("")

        results = await rglob_async("*.py", tmp_path)

        assert [p.relative_to(tmp_path).as_posix() for p in results] == [
            "tools/third_party/lib/lib.py"
        ]
