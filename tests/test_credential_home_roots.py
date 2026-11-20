"""Credential stores behind a symlinked home root, and below the passwd home (#1030).

The deny-list knew a user home only by its spelling (``^/home/[^/]+/`` and the
others in ``PathValidator.USER_HOMES``) plus the server's ``$HOME``. Two gaps:

- **A symlinked home root** (BSD: ``/home -> /usr/home``). The walkers judge
  RESOLVED forms, and ``/usr/home/bob/.ssh`` matches no home pattern, so a walk
  of ``/home/bob`` descended into ``.ssh``. Each root's resolved form is now a
  home root too, resolved once per build (no per-call cost).
- **``$HOME`` that isn't the passwd home.** Only ``$HOME``'s stores were
  recorded as linked, so the real home's ``~/.ssh -> /data/keys`` was missed at
  its target. The passwd home is now a home like ``$HOME``, and its store links
  are part of the cache key.

Other users' linked stores (``/home/bob/.ssh -> /data/bob``) stay matched by
spelling only (documented in SECURITY.md): finding them would mean reading
every user's home.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from pyeye import validation
from pyeye.async_utils import filtered_rglob
from pyeye.validation import PathValidator, credential_path, restricted_dir

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks and passwd")


@pytest.fixture
def homes(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., None]]:
    """Set ``$HOME``, the passwd home and the home roots; clear the store cache."""

    def set_homes(
        home: Path, passwd: Path | None = None, roots: tuple[str, ...] | None = None
    ) -> None:
        monkeypatch.setattr(Path, "home", lambda: home)
        # raising=False: the same fixture runs against code without it (red check).
        monkeypatch.setattr(
            validation, "_passwd_home", lambda: passwd and passwd.as_posix(), raising=False
        )
        if roots is not None:
            monkeypatch.setattr(PathValidator, "USER_HOMES", roots)
        validation._credential_pattern.cache_clear()

    validation._resolved_roots.clear()
    yield set_homes
    monkeypatch.undo()
    validation._resolved_roots.clear()
    validation._credential_pattern.cache_clear()


def _bsd_homes(tmp_path: Path) -> tuple[Path, Path]:
    """``<tmp>/home -> <tmp>/usr/home``, holding bob's home; returns (link, real root)."""
    real = tmp_path / "usr" / "home"
    (real / "bob" / ".ssh").mkdir(parents=True)
    (real / "bob" / ".ssh" / "id_rsa").write_text("", encoding="utf-8")
    (real / "bob" / "proj").mkdir()
    (real / "bob" / "proj" / "mod.py").write_text("", encoding="utf-8")
    link = tmp_path / "home"
    link.symlink_to(real, target_is_directory=True)
    return link, real


class TestASymlinkedHomeRoot:
    def test_a_store_at_the_resolved_root_is_refused(
        self, tmp_path: Path, homes: Callable[..., None]
    ) -> None:
        link, real = _bsd_homes(tmp_path)
        homes(tmp_path / "me", roots=(f"^{link.as_posix()}/[^/]+/",))

        assert credential_path(real / "bob" / ".ssh" / "id_rsa") == ".ssh"
        assert restricted_dir(real / "bob" / ".ssh") is True
        assert restricted_dir(real / "bob" / "proj") is False  # only the stores

    def test_a_walk_through_the_link_skips_the_store(
        self, tmp_path: Path, homes: Callable[..., None]
    ) -> None:
        link, _ = _bsd_homes(tmp_path)
        (link / "bob" / ".ssh" / "keys.py").write_text("", encoding="utf-8")
        homes(tmp_path / "me", roots=(f"^{link.as_posix()}/[^/]+/",))

        found = {p.name for p in filtered_rglob("*.py", link / "bob")}

        assert found == {"mod.py"}

    def test_a_single_home_root_resolves_too(
        self, tmp_path: Path, homes: Callable[..., None]
    ) -> None:
        """``^/root/`` is one home, not a directory of them."""
        real = tmp_path / "var" / "rootHome"
        (real / ".aws").mkdir(parents=True)
        link = tmp_path / "root"
        link.symlink_to(real, target_is_directory=True)
        homes(tmp_path / "me", roots=(f"^{link.as_posix()}/",))

        assert credential_path(real / ".aws" / "credentials") == ".aws"
        assert credential_path(real / "proj" / ".aws") is None  # not a home of its own

    def test_every_home_pattern_has_a_root(self) -> None:
        """A pattern the root parser can't read would silently get no resolved form."""
        for pattern in PathValidator.USER_HOMES:
            assert validation._home_root(pattern) is not None, pattern


class TestThePasswdHome:
    @pytest.fixture
    def passwd_home(self, tmp_path: Path) -> tuple[Path, Path]:
        """A passwd home whose ``.ssh`` links to ``<tmp>/keys``; returns (home, keys)."""
        keys = tmp_path / "keys"
        keys.mkdir()
        (keys / "id_rsa").write_text("", encoding="utf-8")
        real_home = tmp_path / "passwd-home"
        real_home.mkdir()
        (real_home / ".ssh").symlink_to(keys, target_is_directory=True)
        return real_home, keys

    def test_its_linked_store_is_refused_at_its_target(
        self, tmp_path: Path, passwd_home: tuple[Path, Path], homes: Callable[..., None]
    ) -> None:
        real_home, keys = passwd_home
        homes(tmp_path / "env-home", passwd=real_home)

        assert credential_path(keys / "id_rsa") == ".ssh"
        assert restricted_dir(keys) is True

    def test_its_stores_are_refused_by_spelling(
        self, tmp_path: Path, passwd_home: tuple[Path, Path], homes: Callable[..., None]
    ) -> None:
        real_home, _ = passwd_home
        homes(tmp_path / "env-home", passwd=real_home)

        assert credential_path(real_home / ".aws" / "credentials") == ".aws"

    def test_a_relink_below_it_is_seen_at_the_next_rebuild(
        self, tmp_path: Path, passwd_home: tuple[Path, Path], homes: Callable[..., None]
    ) -> None:
        """A documented limit (#1030 review): the cheap key doesn't stat the passwd home.

        A relink below it is seen when the stores are next rebuilt ($HOME's
        store directories change, or a restart), not at once. A path spelled
        through the store is refused all along.
        """
        real_home, keys = passwd_home
        homes(tmp_path / "env-home", passwd=real_home)
        assert credential_path(keys / "id_rsa") == ".ssh"

        moved = tmp_path / "moved"
        moved.mkdir()
        (real_home / ".ssh").unlink()
        (real_home / ".ssh").symlink_to(moved, target_is_directory=True)
        assert credential_path(real_home / ".ssh" / "id_rsa") == ".ssh"  # spelled: always

        validation._credential_pattern.cache_clear()  # what the next rebuild does
        assert credential_path(moved / "id_rsa") == ".ssh"

    def test_the_cheap_key_never_stats_it(
        self, tmp_path: Path, passwd_home: tuple[Path, Path], homes: Callable[..., None]
    ) -> None:
        """A passwd home on a dead mount mustn't hang every check (#1030 review).

        The per-call key stats ``$HOME``'s store directories only; the passwd
        home is compared by its cached value, and read by a rebuild.
        """
        real_home, _ = passwd_home
        homes(tmp_path / "env-home", passwd=real_home)

        _, times = validation._dir_key(validation._env_homes())
        assert len(times) == len(validation._STORE_LINK_DIRS)


def test_another_users_linked_store_is_a_known_limit(
    tmp_path: Path, homes: Callable[..., None]
) -> None:
    """Pinned (SECURITY.md): another user's store link is matched by spelling only."""
    target = tmp_path / "data" / "bob"
    target.mkdir(parents=True)
    root = tmp_path / "users"
    (root / "bob").mkdir(parents=True)
    (root / "bob" / ".ssh").symlink_to(target, target_is_directory=True)
    homes(tmp_path / "me", roots=(f"^{root.as_posix()}/[^/]+/",))

    assert credential_path(root / "bob" / ".ssh" / "id_rsa") == ".ssh"  # by spelling
    assert credential_path(target / "id_rsa") is None  # its target: not matched


class TestReviewFindings:
    """The #1051 review: availability and fail-open cases (#1030)."""

    def test_a_root_is_resolved_once_and_never_under_the_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, homes: Callable[..., None]
    ) -> None:
        link, real = _bsd_homes(tmp_path)
        homes(tmp_path / "me", roots=(f"^{link.as_posix()}/[^/]+/",))
        original = validation.normalize_path
        resolves: list[bool] = []

        def watched(path):  # type: ignore[no-untyped-def]
            if Path(path) == link:
                resolves.append(validation._credential_pattern._lock.locked())
            return original(path)

        monkeypatch.setattr(validation, "normalize_path", watched)
        for _ in range(3):  # three rebuilds
            validation._credential_pattern.cache_clear()
            assert credential_path(real / "bob" / ".ssh" / "id_rsa") == ".ssh"

        assert resolves == [False]  # once, and the lock wasn't held

    def test_a_failed_root_resolve_keeps_the_spelling_and_is_retried(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        homes: Callable[..., None],
    ) -> None:
        link, real = _bsd_homes(tmp_path)
        homes(tmp_path / "me", roots=(f"^{link.as_posix()}/[^/]+/",))
        original = validation.normalize_path

        def failing(path):  # type: ignore[no-untyped-def]
            if Path(path) == link:
                raise OSError("stale NFS file handle")
            return original(path)

        monkeypatch.setattr(validation, "normalize_path", failing)
        with caplog.at_level("WARNING", logger="pyeye.validation"):
            assert credential_path(link / "bob" / ".ssh" / "id_rsa") == ".ssh"  # spelled
        assert "can't resolve the home root" in caplog.text
        assert credential_path(real / "bob" / ".ssh" / "id_rsa") is None  # not yet

        monkeypatch.setattr(validation, "normalize_path", original)
        validation._credential_pattern.cache_clear()  # the next rebuild retries
        assert credential_path(real / "bob" / ".ssh" / "id_rsa") == ".ssh"

    def test_a_root_resolving_to_slash_adds_nothing(
        self, tmp_path: Path, homes: Callable[..., None]
    ) -> None:
        link = tmp_path / "home"
        link.symlink_to("/", target_is_directory=True)
        homes(tmp_path / "me", roots=(f"^{link.as_posix()}/[^/]+/",))

        assert credential_path("/opt/.ssh/id_rsa") is None  # not ^/[^/]+/

    def test_home_slash_still_has_a_cheap_key(self) -> None:
        """``"/".rstrip("/")`` is empty: the key used to stat ``""`` and see nothing."""
        _, times = validation._dir_key(("/",))
        assert times[0] is not None


class TestThePasswdLookup:
    @staticmethod
    def _entry(pw_dir: str):  # type: ignore[no-untyped-def]
        return type("pw", (), {"pw_dir": pw_dir})()

    def test_a_failure_is_retried_not_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LDAP down at start-up must not blind the deny-list for good (fails open)."""
        import pwd

        calls: list[str] = []
        results: list = [KeyError("uid not found"), self._entry("/home/real")]

        def getpwuid(_uid: int):  # type: ignore[no-untyped-def]
            calls.append("x")
            result = results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        now = [1000.0]
        monkeypatch.setattr(pwd, "getpwuid", getpwuid)
        monkeypatch.setattr(validation.time, "monotonic", lambda: now[0])
        lookup = validation._PasswdHome()

        assert lookup() is None
        assert lookup() is None and len(calls) == 1  # backed off: no second lookup yet
        now[0] += validation._PASSWD_RETRY_FIRST_S + 0.1
        assert lookup() == "/home/real" and len(calls) == 2
        assert lookup() == "/home/real" and len(calls) == 2  # a success is kept

    @pytest.mark.parametrize("pw_dir", ["", "relative/home"])
    def test_an_empty_or_relative_home_is_no_home(
        self, monkeypatch: pytest.MonkeyPatch, pw_dir: str
    ) -> None:
        """``Path("")`` is the working directory: it would make the project a home."""
        import pwd

        monkeypatch.setattr(pwd, "getpwuid", lambda _uid: self._entry(pw_dir))

        assert validation._PasswdHome()() is None

    def test_a_recovered_lookup_rebuilds_the_stores(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, homes: Callable[..., None]
    ) -> None:
        real_home = tmp_path / "passwd-home"
        real_home.mkdir()
        homes(tmp_path / "env-home")
        answer: list[str | None] = [None]
        monkeypatch.setattr(validation, "_passwd_home", lambda: answer[0])
        assert credential_path(real_home / ".aws" / "credentials") is None

        answer[0] = real_home.as_posix()  # the directory came back

        assert credential_path(real_home / ".aws" / "credentials") == ".aws"


class TestALookupInFlight:
    """The #1051 final review: a check during the FIRST lookup must not fail open (#1030)."""

    def test_a_concurrent_check_waits_and_refuses_the_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, homes: Callable[..., None]
    ) -> None:
        import pwd
        import threading

        svc = tmp_path / "svc"  # the passwd home, outside every home root
        svc.mkdir()
        homes(tmp_path / "srv")  # $HOME=/srv-like
        entered, release = threading.Event(), threading.Event()

        def slow_getpwuid(_uid: int):  # type: ignore[no-untyped-def]
            entered.set()
            assert release.wait(5)
            return type("pw", (), {"pw_dir": svc.as_posix()})()

        monkeypatch.setattr(pwd, "getpwuid", slow_getpwuid)
        lookup = validation._PasswdHome()
        monkeypatch.setattr(validation, "_passwd_home", lookup)
        first = threading.Thread(target=lookup)
        first.start()
        assert entered.wait(5)  # the first lookup is now in flight

        answers: list[str | None] = []
        check = threading.Thread(
            target=lambda: answers.append(credential_path(svc / ".ssh" / "id_rsa"))
        )
        check.start()
        check.join(0.3)
        assert check.is_alive()  # it waits for the lookup rather than answering early
        release.set()
        check.join(5)
        first.join(5)

        assert answers == [".ssh"]

    def test_a_hung_lookup_bounds_the_wait(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Past the wait the answer is None (documented): one hang can't stall every check."""
        import threading
        import time as real_time

        monkeypatch.setattr(validation, "_PASSWD_WAIT_S", 0.2)
        lookup = validation._PasswdHome()
        lookup._lock.acquire()  # a lookup stuck in another thread
        try:
            start = real_time.monotonic()
            assert lookup() is None
            assert real_time.monotonic() - start < 2
        finally:
            lookup._lock.release()
        assert threading.active_count() >= 1
