"""The deny-list covers boot and secrets dirs, and credential stores in user homes (#909).

The maintainer's ruling:

- SYSTEM dirs, anchored like ``/etc``: ``/boot``, ``/run/secrets``,
  ``/var/run/secrets``, ``/var/root``, ``/private/var/root``. Refused, pruned in
  walks, and they define ancestors (``/run``, ``/var``...). ``/var/lib`` stays out
  (Jenkins workspaces, Docker volumes live there).
- CREDENTIAL stores (``.ssh``, ``.aws``, ...) directly below ANY user home
  (``/home/<u>``, ``/Users/<u>``, ``/root`` or the server's own home): refused and
  pruned, but they define NO ancestors, so a scan of ``~`` or ``/home`` works and
  skips them. A project inside one is refused.

POSIX-only: the deny-list names POSIX paths.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from pyeye.exceptions import ValidationError
from pyeye.validation import PathValidator, credential_path, restricted_dir, unwalkable_root

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="the deny-list names POSIX system directories"
)

REFUSED = "restricted location"
SYSTEM = ["/boot/grub/grub.cfg", "/run/secrets/db", "/var/run/secrets/k8s/token", "/var/root/x"]


@pytest.fixture
def home_at(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[Path], None]]:
    """Set the server's own home (``Path.home()``), rebuilding the cached pattern."""
    from pyeye import validation

    def set_home(home: Path) -> None:
        monkeypatch.setattr(Path, "home", lambda: home)
        validation._credential_pattern.cache_clear()

    yield set_home
    monkeypatch.undo()
    validation._credential_pattern.cache_clear()


def _refused(path: str, root: str = "/tmp") -> None:
    with pytest.raises(ValidationError, match=REFUSED):
        PathValidator.validate_final(path, root)


class TestSystemDirs:
    @pytest.mark.parametrize(
        "path",
        [
            *SYSTEM,
            "/private/var/root/x",
            "/private/var/run/secrets/k8s/token",
            "/BOOT",
            "/run/secrets",
        ],
    )
    def test_refused(self, path: str) -> None:
        _refused(path)

    @pytest.mark.parametrize(
        "path", ["/var/lib/jenkins/workspace/proj", "/var/www/app", "/run/user/1000/x"]
    )
    def test_neighbours_pass(self, path: str) -> None:
        PathValidator.validate_final(path, "/tmp")

    @pytest.mark.parametrize(
        "root", ["/run", "/var", "/var/run", "/private/var", "/private/var/run"]
    )
    def test_their_ancestors_are_refused_as_scan_roots(self, root: str) -> None:
        with pytest.raises(ValidationError, match="ancestor of a restricted location"):
            PathValidator.validate_scan_root(root, "/tmp")

    @pytest.mark.parametrize("path", ["/boot/x", "/run/secrets", "/var/root/y"])
    def test_walks_prune_them(self, path: str) -> None:
        assert restricted_dir(path)


CREDENTIALS = [
    "/home/u/.ssh/id_rsa",
    "/home/u/.ssh",
    "/home/u/.aws/credentials",
    "/home/u/.gnupg/pubring.kbx",
    "/home/u/.config/gcloud/creds.json",
    "/home/u/.azure/x",
    "/home/u/.kube/config",
    "/home/u/.docker/config.json",
    "/home/u/.config/gh/hosts.yml",
    "/home/u/.netrc",
    "/home/u/.pypirc",
    "/home/u/.pgpass",
    "/home/u/.git-credentials",
    "/home/u/.npmrc",
    "/Users/u/.ssh/id_ed25519",
    "/root/.aws/credentials",
    "/home/U/.SSH/k",  # case is ignored
]


class TestCredentialStores:
    @pytest.mark.parametrize("path", CREDENTIALS)
    def test_refused(self, path: str) -> None:
        _refused(path)

    @pytest.mark.parametrize("path", CREDENTIALS)
    def test_walks_prune_them(self, path: str) -> None:
        assert restricted_dir(path)

    def test_every_store_is_covered(self) -> None:
        for name in PathValidator.CREDENTIAL_PATHS:
            assert credential_path(f"/home/someone/{name}") == name

    @pytest.mark.parametrize(
        "path",
        [
            "/home/u/proj/.ssh/fixture_key",  # a project's own fixture, not the home's
            "/home/u/.sshx/x",
            "/home/u/.config/other",
            "/home/u/src/.aws-tools/x",
            "/srv/.ssh/x",  # not a user home
        ],
    )
    def test_look_alikes_pass(self, path: str) -> None:
        PathValidator.validate_final(path, "/tmp")
        assert not restricted_dir(path)

    def test_a_project_inside_a_store_is_refused(self) -> None:
        _refused("/home/u/.config/gh/x/proj")

    def test_a_relative_path_into_a_store_is_refused(self) -> None:
        _refused(".ssh/id_rsa", root="/home/u")

    @pytest.mark.parametrize("root", ["/home", "/home/u", "/Users", "/Users/u"])
    def test_they_define_no_ancestors(self, root: str) -> None:
        """A scan of ~, /home or /Users works and skips the stores."""
        PathValidator.validate_scan_root(root, "/tmp")
        assert not unwalkable_root(root)

    def test_a_home_created_later_is_covered(self) -> None:
        """Matched by pattern, never enumerated: nothing to go stale."""
        assert credential_path("/home/user-added-after-start/.ssh/key") == ".ssh"

    def test_the_servers_own_home_outside_the_roots(self, home_at: Callable[[Path], None]) -> None:
        home_at(Path("/var/lib/jenkins"))

        assert credential_path("/var/lib/jenkins/.ssh/id_rsa") == ".ssh"
        assert credential_path("/var/lib/other/.ssh/id_rsa") is None


def test_a_symlink_into_a_store_is_refused(tmp_path: Path, home_at: Callable[[Path], None]) -> None:
    """The resolved form is checked: a project symlink into ~/.ssh is caught."""
    home = tmp_path / "home" / "u"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_rsa").write_text("k", encoding="utf-8")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "keys").symlink_to(home / ".ssh", target_is_directory=True)
    home_at(home)

    with pytest.raises(ValidationError, match=REFUSED):
        PathValidator.validate_final("keys/id_rsa", proj)


def test_a_home_scan_skips_the_stores(tmp_path: Path, home_at: Callable[[Path], None]) -> None:
    """Defence in depth: walking a home prunes its credential stores."""
    from pyeye.async_utils import pruned_rglob

    home = tmp_path / "u"
    for sub in ("proj", ".ssh", ".config/gh", ".config/other"):
        (home / sub).mkdir(parents=True)
        (home / sub / "x.py").write_text("", encoding="utf-8")
    home_at(home)

    found = {p.parent.name for p in pruned_rglob("x.py", home)}

    assert found == {"proj", "other"}


class TestReviewFollowUps:
    """The #949 re-review's two follow-ups."""

    def test_a_project_path_refusal_names_project_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """resolve_at checked ``file`` first, so it blamed the wrong argument."""
        import asyncio

        from mcp.server.mcpserver.exceptions import ToolError

        from pyeye.mcp.server import mcp

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "l_tmp").symlink_to("/tmp", target_is_directory=True)
        monkeypatch.chdir(tmp_path)
        args = {"file": "x.py", "line": 1, "column": 0, "project_path": "proj/l_tmp/../etc"}

        with pytest.raises(ToolError, match="Invalid project_path"):
            asyncio.run(mcp.call_tool("resolve_at", args))

    @pytest.mark.parametrize("target", ["/etc", "lnk"])
    def test_get_analyzer_refuses_a_restricted_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
    ) -> None:
        """Defence in depth: an internal caller that skips the tools' check."""
        from pyeye.project_manager import ProjectManager

        (tmp_path / "lnk").symlink_to("/etc", target_is_directory=True)
        monkeypatch.chdir(tmp_path)
        manager = ProjectManager(max_projects=2)
        try:
            with pytest.raises(ValidationError, match=REFUSED):
                manager.get_analyzer(target)
            assert manager.analyzers == {}
        finally:
            manager.cleanup_all()


class TestReviewSymlinkedHome:
    """#956 review: ``$HOME`` is a symlink (NFS/autofs ``/home/u`` -> ``/data/u``).

    The home was added only as spelled, so the RESOLVED forms (which the
    resolved check and every walk see) named no home: symlinks into the real
    home's ``.ssh`` passed, and a walk from ``$HOME`` didn't prune it.
    """

    @pytest.fixture
    def homes(self, tmp_path: Path, home_at: Callable[[Path], None]) -> tuple[Path, Path]:
        real = tmp_path / "data" / "u"
        (real / ".ssh").mkdir(parents=True)
        (real / ".ssh" / "k.py").write_text("KEY = 1\n", encoding="utf-8")
        (real / ".aws").mkdir()
        (real / ".aws" / "x.py").write_text("", encoding="utf-8")
        (real / "proj").mkdir()
        (real / "proj" / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        link = tmp_path / "homelink"
        link.symlink_to(real, target_is_directory=True)
        home_at(link)
        return link, real

    def test_validate_final(self, homes: tuple[Path, Path], tmp_path: Path) -> None:
        link, real = homes
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "keys").symlink_to(real / ".ssh", target_is_directory=True)
        for path, root in [
            ("keys/k.py", proj),
            ((real / ".ssh" / "k.py").as_posix(), proj),
            ((link / ".ssh" / "k.py").as_posix(), proj),
        ]:
            _refused(str(path), root=str(root))

    def test_resolve_at_and_project_path(self, homes: tuple[Path, Path]) -> None:
        import asyncio

        from mcp.server.mcpserver.exceptions import ToolError

        from pyeye.mcp.server import mcp

        _link, real = homes
        for tool, args in [
            (
                "resolve_at",
                {
                    "file": (real / ".ssh" / "k.py").as_posix(),
                    "line": 1,
                    "column": 0,
                    "project_path": (real / "proj").as_posix(),
                },
            ),
            ("resolve", {"identifier": "k", "project_path": (real / ".ssh").as_posix()}),
        ]:
            with pytest.raises(ToolError, match=REFUSED):
                asyncio.run(mcp.call_tool(tool, args))

    def test_get_analyzer(self, homes: tuple[Path, Path]) -> None:
        from pyeye.project_manager import ProjectManager

        _link, real = homes
        manager = ProjectManager(max_projects=2)
        try:
            with pytest.raises(ValidationError, match=REFUSED):
                manager.get_analyzer((real / ".ssh").as_posix())
        finally:
            manager.cleanup_all()

    @pytest.mark.parametrize("start", ["link", "real"])
    def test_a_walk_from_either_name_prunes_the_stores(
        self, homes: tuple[Path, Path], start: str
    ) -> None:
        from pyeye.async_utils import filtered_rglob

        link, real = homes
        root = link if start == "link" else real

        found = {p.parent.name for p in filtered_rglob("*.py", root)}

        assert found == {"proj"}


class TestReviewSymlinkedFiles:
    """#956 review: a project FILE symlinked into a store was read during a scan."""

    def test_a_scan_skips_files_linked_into_a_store(
        self, tmp_path: Path, home_at: Callable[[Path], None]
    ) -> None:
        from pyeye.async_utils import filtered_rglob, pruned_rglob

        home = tmp_path / "u"
        (home / ".aws").mkdir(parents=True)
        (home / ".aws" / "credentials").write_text("[default]\n", encoding="utf-8")
        (home / ".netrc").write_text("machine x\n", encoding="utf-8")
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "ok.py").write_text("", encoding="utf-8")
        (proj / "netrc.py").symlink_to(home / ".netrc")
        (proj / "creds.py").symlink_to(home / ".aws" / "credentials")
        (proj / "aws").symlink_to(home / ".aws", target_is_directory=True)
        home_at(home)

        for walk in (filtered_rglob, pruned_rglob):
            assert {p.name for p in walk("*", proj)} == {"ok.py"}, walk.__name__

    def test_a_file_linked_to_etc_is_skipped_too(self, tmp_path: Path) -> None:
        from pyeye.async_utils import filtered_rglob

        (tmp_path / "ok.py").write_text("", encoding="utf-8")
        (tmp_path / "hosts.py").symlink_to("/etc/hosts")

        assert {p.name for p in filtered_rglob("*.py", tmp_path)} == {"ok.py"}

    def test_control_an_ordinary_symlinked_file_is_kept(self, tmp_path: Path) -> None:
        from pyeye.async_utils import filtered_rglob

        (tmp_path / "real.py").write_text("", encoding="utf-8")
        (tmp_path / "alias.py").symlink_to(tmp_path / "real.py")

        assert {p.name for p in filtered_rglob("*.py", tmp_path)} == {"real.py", "alias.py"}
