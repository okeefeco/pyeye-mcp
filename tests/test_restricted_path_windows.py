"""``restricted_path`` on Windows: only a link loop fails closed (#1005).

A strict resolve fails on Windows for files Jedi reads fine: access denied on a
parent, a ``WindowsApps`` app-exec link, an unusual name. #999 counted every
such error as restricted, so those files were refused by mistake. The
credential stores still apply on Windows (below the server's own home), so the
check isn't skipped: a non-loop error falls back to a non-strict resolve, which
is still checked. POSIX keeps failing closed on every error.

The policy tests run on every OS by patching ``resolver._ON_WINDOWS`` and the
strict resolve; the last class runs on Windows only, against the real system.
"""

from __future__ import annotations

import errno
import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from pyeye import resolver, validation
from pyeye.resolver import restricted_path


class _WinError(OSError):
    """An ``OSError`` carrying a Windows error code, on any OS."""

    def __init__(self, winerror: int) -> None:
        super().__init__(None, "simulated Windows error")
        self.winerror = winerror


@pytest.fixture
def home_at(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[Path], None]]:
    def set_home(home: Path) -> None:
        monkeypatch.setattr(Path, "home", lambda: home)
        validation._credential_pattern.cache_clear()

    yield set_home
    monkeypatch.undo()
    validation._credential_pattern.cache_clear()


def _explain(path: Path) -> str:
    """What ``restricted_path`` saw for *path*, so a failure explains itself (#1019)."""
    try:
        strict: object = resolver.normalize_path_strict(path)
    except BaseException as exc:  # noqa: BLE001 - reported, not handled
        strict = f"{type(exc).__name__}: {exc} (winerror={getattr(exc, 'winerror', None)})"
    try:
        loose: object = resolver.normalize_path(path)
    except BaseException as exc:  # noqa: BLE001
        loose = f"{type(exc).__name__}: {exc}"
    stores = validation._credential_pattern()
    return (
        f"path={path.as_posix()!r} strict={strict!r} non_strict={loose!r} "
        f"home={Path.home().as_posix()!r} pattern={stores.pattern.pattern!r} "
        f"linked={stores.linked!r}"
    )


def _strict_raises(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    def fail(_path: object) -> Path:
        raise exc

    monkeypatch.setattr(resolver, "normalize_path_strict", fail)


class TestWindowsPolicy:
    @pytest.mark.parametrize(
        "exc",
        [PermissionError(errno.EACCES, "access denied"), _WinError(5), _WinError(123)],
        ids=["access-denied", "winerror-5", "invalid-name"],
    )
    def test_a_non_loop_error_falls_back_and_is_not_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exc: OSError
    ) -> None:
        monkeypatch.setattr(resolver, "_ON_WINDOWS", True)
        _strict_raises(monkeypatch, exc)

        assert restricted_path(tmp_path / "readable.py") is False

    def test_the_fallback_is_still_checked(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        home_at: Callable[[Path], None],
    ) -> None:
        """A credential store is refused even when the strict resolve failed."""
        home_at(tmp_path / "home")
        monkeypatch.setattr(resolver, "_ON_WINDOWS", True)
        _strict_raises(monkeypatch, PermissionError(errno.EACCES, "access denied"))

        assert restricted_path(tmp_path / "home" / ".ssh" / "id_rsa") is True

    def test_a_link_into_a_credential_store_is_refused_by_the_fallback(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        home_at: Callable[[Path], None],
    ) -> None:
        """A junction or reparse point into ~/.ssh whose STRICT resolve fails.

        The non-strict resolve still follows a link Windows can follow, so the
        checked result is the target inside the credential store. A link it
        can't follow can't be opened either, so nothing is read through it.
        """
        home_at(tmp_path / "home")
        monkeypatch.setattr(resolver, "_ON_WINDOWS", True)
        _strict_raises(monkeypatch, PermissionError(errno.EACCES, "access denied"))
        link = tmp_path / "proj" / "junction" / "id_rsa"
        target = tmp_path / "home" / ".ssh" / "id_rsa"
        monkeypatch.setattr(resolver, "normalize_path", lambda p: target if p == link else Path(p))

        assert restricted_path(link) is True

    @pytest.mark.parametrize(
        "exc",
        [OSError(errno.ELOOP, "loop"), _WinError(1921), RuntimeError("loop")],
        ids=["eloop", "winerror-1921", "runtime-error"],
    )
    def test_a_loop_still_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exc: BaseException
    ) -> None:
        monkeypatch.setattr(resolver, "_ON_WINDOWS", True)
        _strict_raises(monkeypatch, exc)

        assert restricted_path(tmp_path / "x.py") is True

    def test_a_failing_fallback_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(resolver, "_ON_WINDOWS", True)
        _strict_raises(monkeypatch, PermissionError(errno.EACCES, "access denied"))

        def fail(_path: object) -> Path:
            raise OSError(errno.EIO, "unreadable")

        monkeypatch.setattr(resolver, "normalize_path", fail)

        assert restricted_path(tmp_path / "x.py") is True


class TestPosixPolicyIsUnchanged:
    @pytest.mark.parametrize(
        "exc",
        [PermissionError(errno.EACCES, "access denied"), OSError(errno.EIO, "io")],
        ids=["access-denied", "io-error"],
    )
    def test_every_error_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exc: OSError
    ) -> None:
        monkeypatch.setattr(resolver, "_ON_WINDOWS", False)
        _strict_raises(monkeypatch, exc)

        assert restricted_path(tmp_path / "x.py") is True


@pytest.mark.skipif(os.name != "nt", reason="the real Windows filesystem")
class TestOnWindows:
    def test_a_plain_file_is_not_refused(self, tmp_path: Path) -> None:
        target = tmp_path / "mod.py"
        target.write_text("X = 1\n", encoding="utf-8")

        assert restricted_path(target) is False

    def test_the_servers_own_credential_store_is_refused(self) -> None:
        target = Path.home() / ".ssh" / "id_rsa"

        assert restricted_path(target) is True, _explain(target)

    def test_a_symlink_loop_is_refused(self, tmp_path: Path) -> None:
        loop = tmp_path / "loop"
        try:
            loop.symlink_to(loop)
        except OSError:
            pytest.skip("this runner can't create symlinks")

        assert restricted_path(loop / "x.py") is True

    def test_a_junction_into_a_credential_store_is_refused(
        self, tmp_path: Path, home_at: Callable[[Path], None]
    ) -> None:
        import subprocess  # nosec B404 - mklink, a fixed argv in a temp dir

        home = tmp_path / "home"
        (home / ".ssh").mkdir(parents=True)
        (home / ".ssh" / "id_rsa").write_text("", encoding="utf-8")
        home_at(home)
        junction = tmp_path / "junction"
        made = subprocess.run(  # nosec B603 B607 - cmd's mklink builtin, fixed arguments
            ["cmd", "/c", "mklink", "/J", str(junction), str(home / ".ssh")],
            capture_output=True,
            check=False,
        )
        if made.returncode != 0:
            pytest.skip("this runner can't create a junction")

        assert restricted_path(junction / "id_rsa") is True

    def test_a_store_that_is_a_junction_is_refused_at_its_target(
        self, tmp_path: Path, home_at: Callable[[Path], None]
    ) -> None:
        """``~/.ssh`` is a junction to another directory: its files resolve there (#1019)."""
        import subprocess  # nosec B404 - mklink, a fixed argv in a temp dir

        keys = tmp_path / "keys"
        keys.mkdir()
        (keys / "id_rsa").write_text("", encoding="utf-8")
        home = tmp_path / "home"
        home.mkdir()
        made = subprocess.run(  # nosec B603 B607 - cmd's mklink builtin, fixed arguments
            ["cmd", "/c", "mklink", "/J", str(home / ".ssh"), str(keys)],
            capture_output=True,
            check=False,
        )
        if made.returncode != 0:
            pytest.skip("this runner can't create a junction")
        home_at(home)

        assert restricted_path(keys / "id_rsa") is True, _explain(keys / "id_rsa")
        assert restricted_path(home / ".ssh" / "id_rsa") is True

    def test_a_windowsapps_alias_is_not_refused(self) -> None:
        local = os.environ.get("LOCALAPPDATA")
        aliases = sorted(Path(local, "Microsoft", "WindowsApps").glob("*.exe")) if local else []
        if not aliases:
            pytest.skip("no WindowsApps app-exec aliases on this runner")

        assert restricted_path(aliases[0]) is False
