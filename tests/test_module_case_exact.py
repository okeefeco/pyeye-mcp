"""A module name matches its file only in the file's exact case (#1047).

``project_layout._module_file_under`` tested ``Path.exists()``, which ignores
case on macOS (APFS/HFS+) and Windows (NTFS). So ``resolve("pkg.Dyn")`` found
``pkg/dyn.py`` and answered "module ``pkg.Dyn``", a module Python can't import:
its import system checks case on those filesystems. #1031's star re-export test
caught it on macOS CI, where ``pkg.Dyn`` should be the class ``pkg.dyn.Dyn``.

Linux CI is case-sensitive, so these tests stand a case-insensitive filesystem
in by patching ``Path.exists`` to match names regardless of case, as APFS and
NTFS do. macOS and Windows CI run the real thing through #1031's test.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from pyeye import project_layout
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.resolve import resolve

_real_exists = Path.exists


def _case_blind_exists(self: Path, *_args: object, **_kwargs: object) -> bool:
    """``Path.exists`` on a case-insensitive filesystem: each part matches any case."""
    if _real_exists(self):
        return True
    path = self.absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        try:
            names = os.listdir(current)
        except OSError:
            return False
        match = next((n for n in names if n.lower() == part.lower()), None)
        if match is None:
            return False
        current = current / match
    return True


@pytest.fixture
def case_blind(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A case-insensitive filesystem, and a mapper that knows it is on one."""
    monkeypatch.setattr(Path, "exists", _case_blind_exists)
    project_layout.clear_case_caches()
    monkeypatch.setattr(project_layout, "_is_case_sensitive", lambda _base: False)
    yield
    project_layout.clear_case_caches()


def _project(root: Path) -> Path:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("from .dyn import *\n", encoding="utf-8")
    (root / "pkg" / "dyn.py").write_text("class Dyn:\n    pass\n", encoding="utf-8")
    (root / "pkg" / "Sub").mkdir()
    (root / "pkg" / "Sub" / "__init__.py").write_text("", encoding="utf-8")
    return root


class TestOnACaseInsensitiveFilesystem:
    @pytest.mark.usefixtures("case_blind")
    def test_the_stand_in_really_ignores_case(self, tmp_path: Path) -> None:
        _project(tmp_path)

        assert (tmp_path / "pkg" / "Dyn.py").exists()  # the bug's precondition

    @pytest.mark.usefixtures("case_blind")
    def test_a_module_name_in_another_case_finds_no_file(self, tmp_path: Path) -> None:
        root = _project(tmp_path)

        assert project_layout._module_file_under(root, ["pkg", "Dyn"]) is None
        assert project_layout._module_file_under(root, ["pkg", "sub"]) is None  # a package dir
        assert project_layout._module_file_under(root, ["PKG", "dyn"]) is None  # a parent dir

    @pytest.mark.usefixtures("case_blind")
    def test_the_exact_name_still_finds_its_file(self, tmp_path: Path) -> None:
        root = _project(tmp_path)

        assert project_layout._module_file_under(root, ["pkg", "dyn"]) == root / "pkg" / "dyn.py"
        assert (
            project_layout._module_file_under(root, ["pkg", "Sub"])
            == root / "pkg" / "Sub" / "__init__.py"
        )

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("case_blind")
    async def test_a_star_re_export_is_not_taken_for_a_module(self, tmp_path: Path) -> None:
        """#1031's macOS failure: ``pkg.Dyn`` is the class, not a module ``pkg.Dyn``."""
        root = _project(tmp_path)

        result = await resolve("pkg.Dyn", JediAnalyzer(str(root)))

        assert result.get("handle") == "pkg.dyn.Dyn", result
        assert result.get("kind") == "class", result


class TestTheCaseSensitivityProbe:
    def test_a_linux_tmp_dir_is_case_sensitive(self, tmp_path: Path) -> None:
        if os.path.exists(tmp_path.as_posix().swapcase()):
            pytest.skip("this temp directory is on a case-insensitive filesystem")
        project_layout.clear_case_caches()
        cased = tmp_path / "Root"
        cased.mkdir()

        assert project_layout._is_case_sensitive(cased) is True

    def test_a_case_insensitive_directory_is_detected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_layout.clear_case_caches()
        cased = tmp_path / "Root"
        cased.mkdir()
        monkeypatch.setattr(Path, "exists", _case_blind_exists)
        monkeypatch.setattr(
            project_layout.os.path,
            "samefile",
            lambda a, b: Path(a).as_posix().lower() == Path(b).as_posix().lower(),
        )

        assert project_layout._is_case_sensitive(cased) is False

    def test_a_path_with_no_cased_name_is_checked_exactly(self) -> None:
        """Nothing to swap, so the probe can't tell: the exact check runs (the safe side)."""
        project_layout.clear_case_caches()

        assert project_layout._is_case_sensitive(Path("/")) is False

    def test_the_probe_runs_once_per_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_layout.clear_case_caches()
        cased = tmp_path / "Root"
        cased.mkdir()
        project_layout._is_case_sensitive(cased)
        monkeypatch.setattr(
            project_layout.os.path, "samefile", lambda *_a: pytest.fail("probed again")
        )

        project_layout._is_case_sensitive(cased)


class TestTheListingCache:
    @pytest.mark.usefixtures("case_blind")
    def test_a_rename_on_disk_is_seen(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        assert project_layout._exact_case(root, ["pkg", "dyn.py"]) is True

        (root / "pkg" / "dyn.py").rename(root / "pkg" / "Dyn.py")

        assert project_layout._exact_case(root, ["pkg", "dyn.py"]) is False
        assert project_layout._exact_case(root, ["pkg", "Dyn.py"]) is True

    @pytest.mark.usefixtures("case_blind")
    def test_a_settled_directory_is_listed_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _project(tmp_path)
        old = 1_000_000_000
        for directory in (root, root / "pkg"):
            os.utime(directory, ns=(old, old))
        assert project_layout._exact_case(root, ["pkg", "dyn.py"]) is True
        monkeypatch.setattr(project_layout.os, "listdir", lambda _d: pytest.fail("listed again"))

        assert project_layout._exact_case(root, ["pkg", "dyn.py"]) is True

    @pytest.mark.usefixtures("case_blind")
    def test_a_recently_changed_directory_is_listed_again(self, tmp_path: Path) -> None:
        """A change in the same mtime tick as the listing must not be missed."""
        root = _project(tmp_path)
        tick = os.stat(root / "pkg").st_mtime_ns
        assert project_layout._exact_case(root, ["pkg", "dyn.py"]) is True

        (root / "pkg" / "dyn.py").rename(root / "pkg" / "DYN.py")
        os.utime(root / "pkg", ns=(tick, tick))  # the same timestamp the listing saw

        assert project_layout._exact_case(root, ["pkg", "dyn.py"]) is False

    @pytest.mark.usefixtures("case_blind")
    def test_a_missing_directory_has_no_entries(self, tmp_path: Path) -> None:
        assert project_layout._exact_case(tmp_path, ["absent", "x.py"]) is False


def test_a_case_sensitive_root_skips_the_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Linux pays nothing: a case-sensitive root never lists a directory."""
    root = _project(tmp_path)
    project_layout.clear_case_caches()
    monkeypatch.setattr(project_layout, "_is_case_sensitive", lambda _base: True)
    monkeypatch.setattr(project_layout.os, "listdir", lambda _d: pytest.fail("listed"))

    assert project_layout._module_file_under(root, ["pkg", "dyn"]) == root / "pkg" / "dyn.py"


class TestTheEdges:
    def test_the_probe_climbs_to_the_deepest_cased_part(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``<tmp>/Root/123``: ``123`` has no case to swap, so ``Root`` is probed."""
        project_layout.clear_case_caches()
        digits = tmp_path / "Root" / "123"
        digits.mkdir(parents=True)
        probed = []
        real = project_layout.os.path.samefile
        monkeypatch.setattr(
            project_layout.os.path,
            "samefile",
            lambda a, b: probed.append(Path(b).name) or real(a, b),
        )
        monkeypatch.setattr(Path, "exists", _case_blind_exists)

        project_layout._is_case_sensitive(digits)

        assert probed == ["rOOT"]

    def test_a_probe_that_errors_takes_the_exact_check(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_layout.clear_case_caches()
        cased = tmp_path / "Root"
        cased.mkdir()
        monkeypatch.setattr(Path, "exists", _case_blind_exists)

        def unreadable(*_a: object) -> bool:
            raise PermissionError("no access")

        monkeypatch.setattr(project_layout.os.path, "samefile", unreadable)

        assert project_layout._is_case_sensitive(cased) is False

    def test_an_unstattable_or_unlistable_directory_has_no_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert project_layout._entries(tmp_path / "absent") is None

        def unlistable(_d: object) -> list[str]:
            raise PermissionError("no access")

        monkeypatch.setattr(project_layout.os, "listdir", unlistable)

        assert project_layout._entries(tmp_path) is None

    def test_the_listing_cache_is_bounded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_layout.clear_case_caches()
        monkeypatch.setattr(project_layout, "_LISTINGS_MAX", 2)
        old = 1_000_000_000
        dirs = [tmp_path / name for name in ("a", "b", "c")]
        for directory in dirs:
            directory.mkdir()
            os.utime(directory, ns=(old, old))
            project_layout._entries(directory)

        assert list(project_layout._listings) == [d.as_posix() for d in dirs[1:]]
        project_layout.clear_case_caches()
