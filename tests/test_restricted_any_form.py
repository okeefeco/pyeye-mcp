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
