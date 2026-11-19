"""A result is refused when ANY form of its file is restricted (#1019).

#999's ``restricted_path`` checked only the resolved form, and the credential
stores matched only by their spelling below a user home. Two routes slipped
through:

- a store that is itself a link (``~/.ssh -> /data/keys``): its files resolve to
  ``/data/keys/...``, spelled below no home, so neither ``restricted_path`` nor
  the walkers' ``restricted_dir`` refused them;
- a path spelled inside a store whose resolve lands elsewhere: the input checks
  (``validate_final``) refuse every form of a path, spelled and resolved, but
  the result check looked at one.

Both checks now share one predicate (:func:`pyeye.validation.restricted_reason`),
and the store match also covers each store's own resolved location below the
server's home. POSIX only: the links need no privileges there; the Windows
junction case is in ``test_restricted_path_windows.py``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from pyeye import validation
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.resolve import resolve
from pyeye.resolver import restricted_path
from pyeye.validation import (
    PathValidator,
    ValidationError,
    credential_path,
    restricted_dir,
    restricted_reason,
)

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")


@pytest.fixture
def home_at(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[Path], None]]:
    def set_home(home: Path) -> None:
        monkeypatch.setattr(Path, "home", lambda: home)
        validation._credential_pattern.cache_clear()

    yield set_home
    monkeypatch.undo()
    validation._credential_pattern.cache_clear()


@pytest.fixture
def linked_store(tmp_path: Path, home_at: Callable[[Path], None]) -> Path:
    """``<home>/.ssh`` is a symlink to ``<tmp>/keys``, which holds ``id_rsa``; returns keys."""
    keys = tmp_path / "keys"
    keys.mkdir()
    (keys / "id_rsa").write_text("", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    (home / ".ssh").symlink_to(keys, target_is_directory=True)
    home_at(home)
    return keys


class TestAStoreThatIsALink:
    def test_its_target_is_the_store(self, linked_store: Path) -> None:
        assert credential_path(linked_store / "id_rsa") == ".ssh"
        assert credential_path(linked_store) == ".ssh"

    def test_a_result_resolving_into_it_is_refused(self, linked_store: Path) -> None:
        assert restricted_path(linked_store / "id_rsa") is True

    def test_the_walkers_prune_it(self, linked_store: Path) -> None:
        assert restricted_dir(linked_store.resolve()) is True

    def test_a_sibling_of_its_target_is_not_refused(self, linked_store: Path) -> None:
        other = linked_store.parent / "keys-other"
        other.mkdir()

        assert restricted_path(other / "mod.py") is False
        assert credential_path(other) is None

    @pytest.mark.asyncio
    async def test_a_project_link_into_its_target_is_refused_end_to_end(
        self, tmp_path: Path, linked_store: Path
    ) -> None:
        pkg = linked_store / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "keys.py").write_text("TOKEN = 'LEAKMARK'\n", encoding="utf-8")
        project = tmp_path / "proj"
        project.mkdir()
        (project / "app.py").write_text("import storemod.keys\n", encoding="utf-8")
        (project / "storemod").symlink_to(pkg, target_is_directory=True)

        result = await resolve("storemod.keys", JediAnalyzer(str(project)))

        assert result["found"] is False, result
        assert "LEAKMARK" not in repr(result)


class TestTheSpelledFormIsChecked:
    def test_a_path_spelled_in_a_store_that_resolves_elsewhere(
        self, tmp_path: Path, home_at: Callable[[Path], None]
    ) -> None:
        elsewhere = tmp_path / "elsewhere" / "mod.py"
        elsewhere.parent.mkdir()
        elsewhere.write_text("", encoding="utf-8")
        ssh = tmp_path / "home" / ".ssh"
        ssh.mkdir(parents=True)
        (ssh / "link.py").symlink_to(elsewhere)
        home_at(tmp_path / "home")

        assert restricted_path(ssh / "link.py") is True
        assert restricted_path(elsewhere) is False

    def test_a_link_into_a_store_is_still_refused(
        self, tmp_path: Path, home_at: Callable[[Path], None]
    ) -> None:
        ssh = tmp_path / "home" / ".ssh"
        ssh.mkdir(parents=True)
        (ssh / "id_rsa").write_text("", encoding="utf-8")
        link = tmp_path / "proj" / "id_rsa"
        link.parent.mkdir()
        link.symlink_to(ssh / "id_rsa")
        home_at(tmp_path / "home")

        assert restricted_path(link) is True

    def test_a_symlinked_project_root_still_passes(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        real.mkdir()
        (real / "mod.py").write_text("", encoding="utf-8")
        (tmp_path / "alias").symlink_to(real, target_is_directory=True)

        assert restricted_path(tmp_path / "alias" / "mod.py") is False


class TestOnePredicateForInputsAndResults:
    """``validate_final`` and ``restricted_path`` refuse exactly the same paths."""

    @pytest.mark.parametrize(
        ("rel", "refused"),
        [
            ("home/.ssh/id_rsa", True),
            ("home/.ssh/link.py", True),  # spelled in a store, resolves outside
            ("proj/id_rsa", True),  # a link into a store
            ("keys/id_rsa", True),  # the target of a store that is a link
            ("proj/mod.py", False),
            ("elsewhere/mod.py", False),
        ],
    )
    def test_they_agree(
        self, tmp_path: Path, home_at: Callable[[Path], None], rel: str, refused: bool
    ) -> None:
        home = tmp_path / "home"
        (tmp_path / "keys").mkdir()
        (tmp_path / "keys" / "id_rsa").write_text("", encoding="utf-8")
        (tmp_path / "elsewhere").mkdir()
        (tmp_path / "elsewhere" / "mod.py").write_text("", encoding="utf-8")
        (home / ".ssh").mkdir(parents=True)
        (home / ".ssh" / "id_rsa").write_text("", encoding="utf-8")
        (home / ".ssh" / "link.py").symlink_to(tmp_path / "elsewhere" / "mod.py")
        (home / ".aws").symlink_to(tmp_path / "keys", target_is_directory=True)
        (tmp_path / "proj").mkdir()
        (tmp_path / "proj" / "mod.py").write_text("", encoding="utf-8")
        (tmp_path / "proj" / "id_rsa").symlink_to(home / ".ssh" / "id_rsa")
        home_at(home)
        path = tmp_path / rel

        try:
            PathValidator.validate_final(path, tmp_path / "proj")
            input_refused = False
        except ValidationError:
            input_refused = True

        assert restricted_path(path) is refused
        assert input_refused is refused

    def test_every_restricted_pattern_is_a_directory_the_predicate_tests(self) -> None:
        """The predicate tests ``_RESTRICTED_DIRS``, so no pattern may fall outside it.

        Each pattern must be ``^`` + a literal directory + ``/``: an unanchored
        or non-literal one would be dropped from ``_RESTRICTED_DIRS`` and so
        silently stop applying to inputs, results and walks alike.
        """
        for pattern in PathValidator.RESTRICTED_TARGETS:
            directory = pattern[1:-1]
            assert pattern == f"^{directory}/", pattern
            assert re.escape(directory).replace("\\/", "/") == directory, pattern
        assert (
            tuple(p[1:-1] for p in PathValidator.RESTRICTED_TARGETS) == validation._RESTRICTED_DIRS
        )

    def test_the_predicate_names_why(self, tmp_path: Path, home_at: Callable[[Path], None]) -> None:
        home_at(tmp_path / "home")

        assert restricted_reason("/etc/passwd") == "^/etc/"
        assert restricted_reason("/ETC") == "^/etc/"  # case is ignored (#939)
        assert ".ssh" in (restricted_reason((tmp_path / "home" / ".ssh").as_posix()) or "")
        assert restricted_reason((tmp_path / "proj" / "mod.py").as_posix()) is None


class TestTheStoreCacheIsKeyed:
    """A build is served only for the home and store links it was made from (#1019 review).

    A sweep on a background thread could store a build made under the real home
    after a test had patched its own and cleared the cache, and a store linked
    or relinked after the first build wasn't seen until a restart.
    """

    def test_a_build_for_another_home_is_never_served(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home_at: Callable[[Path], None]
    ) -> None:
        home_at(tmp_path / "first")
        assert credential_path(tmp_path / "first" / ".ssh" / "id_rsa") == ".ssh"

        # No cache_clear: the new home's spelling alone forces a rebuild.
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "second")
        assert credential_path(tmp_path / "second" / ".ssh" / "id_rsa") == ".ssh"

    def test_a_stale_build_stored_after_a_clear_is_not_served(
        self, tmp_path: Path, home_at: Callable[[Path], None]
    ) -> None:
        """The race: a background build for the real home lands after the test's clear."""
        validation._credential_pattern.cache_clear()
        stale_key = validation._store_key()  # the real home
        stale = (stale_key, validation._build_credential_stores(stale_key[0][0]))
        home_at(tmp_path / "home")
        validation._credential_pattern._built = stale

        assert credential_path(tmp_path / "home" / ".aws" / "credentials") == ".aws"

    def test_a_store_linked_after_the_first_build_is_seen(
        self, tmp_path: Path, home_at: Callable[[Path], None]
    ) -> None:
        home = tmp_path / "home"
        home.mkdir()
        home_at(home)
        gpg = tmp_path / "gpg"
        gpg.mkdir()
        assert restricted_path(gpg / "secring.gpg") is False  # built: no link yet

        (home / ".gnupg").symlink_to(gpg, target_is_directory=True)

        assert restricted_path(gpg / "secring.gpg") is True

    def test_a_repointed_store_moves_with_its_link(
        self, tmp_path: Path, home_at: Callable[[Path], None]
    ) -> None:
        """A profile switcher relinks ``~/.aws``: the new target is the store, the old isn't."""
        home = tmp_path / "home"
        home.mkdir()
        first, second = tmp_path / "profile-a", tmp_path / "profile-b"
        first.mkdir()
        second.mkdir()
        (home / ".aws").symlink_to(first, target_is_directory=True)
        home_at(home)
        assert restricted_path(first / "credentials") is True

        (home / ".aws").unlink()
        (home / ".aws").symlink_to(second, target_is_directory=True)

        assert restricted_path(second / "credentials") is True
        assert restricted_path(first / "credentials") is False

    def test_a_relinked_parent_of_a_store_is_seen(
        self, tmp_path: Path, home_at: Callable[[Path], None]
    ) -> None:
        """``.config/gh`` moves when ``~/.config`` is linked elsewhere."""
        home = tmp_path / "home"
        home.mkdir()
        home_at(home)
        config = tmp_path / "dotfiles" / "config"
        (config / "gh").mkdir(parents=True)
        assert restricted_path(config / "gh" / "hosts.yml") is False

        (home / ".config").symlink_to(config, target_is_directory=True)

        assert restricted_path(config / "gh" / "hosts.yml") is True

    def test_the_cheap_key_watches_the_home_and_dot_config(self) -> None:
        assert validation._STORE_LINK_DIRS == ("", ".config")

    def test_an_old_unchanged_home_is_served_without_the_full_check(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        home_at: Callable[[Path], None],
    ) -> None:
        """The walkers' fast path: two ``stat`` calls, no ``readlink`` per store."""
        home = tmp_path / "home"
        (home / ".config").mkdir(parents=True)
        old = 1_000_000_000  # 2001: far older than the recent window
        for directory in (home, home / ".config"):
            os.utime(directory, ns=(old, old))
        home_at(home)
        # A fresh directory's ctime is always recent; take the window away so
        # only the key decides, as for a home that has been quiet a while.
        monkeypatch.setattr(validation, "_RECENT_NS", 0)
        validation._credential_pattern()  # built
        calls = []
        monkeypatch.setattr(validation, "_store_key", lambda: calls.append(1))

        assert credential_path(home / ".ssh" / "id_rsa") == ".ssh"
        assert calls == []

    def test_a_change_in_a_store_directory_forces_the_full_check(
        self, tmp_path: Path, home_at: Callable[[Path], None]
    ) -> None:
        """A new link changes its directory's mtime, so the cheap key changes too."""
        home = tmp_path / "home"
        home.mkdir()
        old = 1_000_000_000
        os.utime(home, ns=(old, old))
        home_at(home)
        keys = tmp_path / "keys"
        keys.mkdir()
        assert restricted_path(keys / "id_rsa") is False

        (home / ".ssh").symlink_to(keys, target_is_directory=True)
        os.utime(home, ns=(old + 1, old + 1))  # still old: only the mtime differs

        assert restricted_path(keys / "id_rsa") is True

    def test_an_mtime_set_back_after_a_relink_is_still_seen(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home_at: Callable[[Path], None]
    ) -> None:
        """``touch -d`` restoring the exact old mtime: the ctime still moves (POSIX)."""
        home = tmp_path / "home"
        home.mkdir()
        old = 1_000_000_000
        os.utime(home, ns=(old, old))
        home_at(home)
        monkeypatch.setattr(validation, "_RECENT_NS", 0)
        keys = tmp_path / "keys"
        keys.mkdir()
        assert restricted_path(keys / "id_rsa") is False

        (home / ".ssh").symlink_to(keys, target_is_directory=True)
        os.utime(home, ns=(old, old))  # the mtime is exactly what the build saw

        assert restricted_path(keys / "id_rsa") is True

    def test_a_repointed_second_hop_outside_the_home_is_a_documented_limit(
        self, tmp_path: Path, home_at: Callable[[Path], None]
    ) -> None:
        """``~/.ssh -> hop -> keys``; repointing ``hop`` (outside ``~``) changes nothing watched.

        Only the store's own link and the directories holding the stores are
        watched. The new target is matched after the next change to ``~`` or
        ``~/.config``, or a restart (SECURITY.md). Paths spelled through
        ``~/.ssh`` are always refused by their spelling.
        """
        home = tmp_path / "home"
        home.mkdir()
        first, second = tmp_path / "keys-a", tmp_path / "keys-b"
        first.mkdir()
        second.mkdir()
        hop = tmp_path / "hop"
        hop.symlink_to(first, target_is_directory=True)
        (home / ".ssh").symlink_to(hop, target_is_directory=True)
        old = 1_000_000_000
        os.utime(home, ns=(old, old))
        home_at(home)
        assert restricted_path(first / "id_rsa") is True

        hop.unlink()
        hop.symlink_to(second, target_is_directory=True)

        assert restricted_path(home / ".ssh" / "id_rsa") is True  # by its spelling
        # The limit, on the cheap path and the full one alike: the full key
        # reads only the store's own link, and ``readlink(~/.ssh)`` is unchanged.
        assert restricted_path(second / "id_rsa") is False

    def test_with_no_home_only_the_fixed_roots_apply(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``Path.home()`` failing (no ``$HOME``) still leaves every fixed user home covered."""

        def no_home() -> Path:
            raise RuntimeError("Could not determine home directory.")

        monkeypatch.setattr(Path, "home", no_home)
        validation._credential_pattern.cache_clear()
        try:
            assert validation._store_key() == ((None, ()), ())
            assert validation._dir_key(None) == (None, ())
            assert credential_path("/home/someone/.ssh/id_rsa") == ".ssh"
            assert credential_path((tmp_path / "x" / ".ssh" / "id_rsa").as_posix()) is None
            assert credential_path("/Users/someone/.aws/credentials") == ".aws"  # served again
        finally:
            monkeypatch.undo()
            validation._credential_pattern.cache_clear()

    def test_every_store_and_its_parents_are_watched(self) -> None:
        assert ".config" in validation._STORE_LINK_PATHS
        assert ".config/gcloud" in validation._STORE_LINK_PATHS
        assert set(PathValidator.CREDENTIAL_PATHS) <= set(validation._STORE_LINK_PATHS)
