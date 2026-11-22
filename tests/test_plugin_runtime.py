"""Unit tests for ``scripts/plugin_runtime.py``: one plugin venv per plugin ROOT (#1136).

Every ``claude --plugin-dir`` session is plugin ``pyeye@inline``, so all of them
share one ``${CLAUDE_PLUGIN_DATA}``.  A single ``.venv`` there held an editable
install of whichever checkout synced first, and parallel worktrees silently ran
each other's code.  The runtime keys the venv on the plugin root instead, syncs
it synchronously when it is missing or stale (no first-run race with the async
setup hook), and warns in the pyeye repo when the plugin isn't this checkout.
"""

from __future__ import annotations

import io
import json
import subprocess  # nosec B404 — only fake CompletedProcess objects here
from pathlib import Path

import pytest

import scripts.plugin_runtime as rt


def _plugin_root(path: Path, lock: str = "lock-v1") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "uv.lock").write_text(lock, encoding="utf-8")
    return path


class FakeUv:
    """Stands in for ``uv sync``: records calls and creates the venv's python."""

    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def __call__(self, cmd, *, env, **_kwargs):  # noqa: ANN001 — subprocess.run shape
        self.calls.append((list(cmd), dict(env)))
        if self.returncode == 0:
            python = rt.venv_python(Path(env["UV_PROJECT_ENVIRONMENT"]))
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, self.returncode)


class TestSlotPerRoot:
    def test_two_roots_get_two_venvs(self, tmp_path: Path) -> None:
        data = tmp_path / "data"
        a = rt.slot_dir(_plugin_root(tmp_path / "a"), data)
        b = rt.slot_dir(_plugin_root(tmp_path / "b"), data)
        assert a != b
        assert a.parent == b.parent == data / "venvs"

    def test_same_root_same_venv(self, tmp_path: Path) -> None:
        root = _plugin_root(tmp_path / "a")
        assert rt.slot_dir(root, tmp_path / "d") == rt.slot_dir(root, tmp_path / "d")

    def test_spelling_of_the_root_does_not_matter(self, tmp_path: Path) -> None:
        root = _plugin_root(tmp_path / "a")
        other_spelling = tmp_path / "a" / ".." / "a"
        assert rt.slot_dir(root, tmp_path / "d") == rt.slot_dir(other_spelling, tmp_path / "d")


class TestEnsure:
    def test_missing_venv_is_synced_into_the_roots_slot(self, tmp_path: Path) -> None:
        root, data, uv = _plugin_root(tmp_path / "root"), tmp_path / "data", FakeUv()
        venv = rt.ensure(root, data, run=uv, out=io.StringIO())
        assert venv == rt.slot_dir(root, data) / ".venv"
        [(cmd, env)] = uv.calls
        assert cmd[:2] == ["uv", "sync"]
        assert {"--frozen", "--no-dev"} <= set(cmd)
        assert "--locked" not in cmd, "--locked is for CI only"
        assert cmd[cmd.index("--project") + 1] == str(root)
        assert env["UV_PROJECT_ENVIRONMENT"] == str(venv)

    def test_up_to_date_venv_is_not_synced_again(self, tmp_path: Path) -> None:
        root, data, uv = _plugin_root(tmp_path / "root"), tmp_path / "data", FakeUv()
        rt.ensure(root, data, run=uv, out=io.StringIO())
        rt.ensure(root, data, run=uv, out=io.StringIO())
        assert len(uv.calls) == 1

    def test_a_changed_lockfile_resyncs(self, tmp_path: Path) -> None:
        root, data, uv = _plugin_root(tmp_path / "root"), tmp_path / "data", FakeUv()
        rt.ensure(root, data, run=uv, out=io.StringIO())
        (root / "uv.lock").write_text("lock-v2", encoding="utf-8")
        rt.ensure(root, data, run=uv, out=io.StringIO())
        assert len(uv.calls) == 2

    def test_a_deleted_venv_resyncs_even_with_a_matching_marker(self, tmp_path: Path) -> None:
        root, data, uv = _plugin_root(tmp_path / "root"), tmp_path / "data", FakeUv()
        venv = rt.ensure(root, data, run=uv, out=io.StringIO())
        rt.venv_python(venv).unlink()
        rt.ensure(root, data, run=uv, out=io.StringIO())
        assert len(uv.calls) == 2

    def test_another_roots_venv_is_never_reused(self, tmp_path: Path) -> None:
        # The #1136 bleed: the second checkout must not get the first one's venv.
        data, uv = tmp_path / "data", FakeUv()
        a = rt.ensure(_plugin_root(tmp_path / "a"), data, run=uv, out=io.StringIO())
        b = rt.ensure(_plugin_root(tmp_path / "b"), data, run=uv, out=io.StringIO())
        assert a != b
        assert len(uv.calls) == 2

    def test_failed_sync_leaves_no_marker(self, tmp_path: Path) -> None:
        root, data = _plugin_root(tmp_path / "root"), tmp_path / "data"
        with pytest.raises(rt.SetupError, match="exit 1"):
            rt.ensure(root, data, run=FakeUv(returncode=1), out=io.StringIO())
        uv = FakeUv()
        rt.ensure(root, data, run=uv, out=io.StringIO())
        assert len(uv.calls) == 1, "a failed sync must be retried next time"

    def test_records_its_root(self, tmp_path: Path) -> None:
        root, data = _plugin_root(tmp_path / "root"), tmp_path / "data"
        rt.ensure(root, data, run=FakeUv(), out=io.StringIO())
        assert (rt.slot_dir(root, data) / "root").read_text(encoding="utf-8") == str(root)

    def test_missing_lockfile_is_an_error(self, tmp_path: Path) -> None:
        (tmp_path / "root").mkdir()
        with pytest.raises(rt.SetupError, match="lockfile"):
            rt.ensure(tmp_path / "root", tmp_path / "d", run=FakeUv(), out=io.StringIO())

    def test_missing_uv_is_an_error(self, tmp_path: Path) -> None:
        def no_uv(*_args, **_kwargs):  # noqa: ANN002, ANN003
            raise FileNotFoundError("uv")

        with pytest.raises(rt.SetupError, match="uv"):
            rt.ensure(_plugin_root(tmp_path / "r"), tmp_path / "d", run=no_uv, out=io.StringIO())


class TestPrune:
    def test_removes_slots_whose_root_is_gone(self, tmp_path: Path) -> None:
        data, uv = tmp_path / "data", FakeUv()
        keep, gone = _plugin_root(tmp_path / "keep"), _plugin_root(tmp_path / "gone")
        rt.ensure(keep, data, run=uv, out=io.StringIO())
        rt.ensure(gone, data, run=uv, out=io.StringIO())
        (gone / "uv.lock").unlink()
        gone.rmdir()
        removed = rt.prune(data)
        assert removed == [rt.slot_dir(gone, data)]
        assert rt.slot_dir(keep, data).is_dir()
        assert not rt.slot_dir(gone, data).exists()

    def test_leaves_slots_it_cannot_attribute(self, tmp_path: Path) -> None:
        # A slot mid-sync has no "root" file yet: never delete it.
        (tmp_path / "data" / "venvs" / "abc").mkdir(parents=True)
        assert rt.prune(tmp_path / "data") == []
        assert (tmp_path / "data" / "venvs" / "abc").is_dir()

    def test_no_data_dir_is_fine(self, tmp_path: Path) -> None:
        assert rt.prune(tmp_path / "nothing") == []


def _pyeye_repo(path: Path, name: str = "pyeye") -> Path:
    (path / ".claude-plugin").mkdir(parents=True)
    (path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": name}), encoding="utf-8"
    )
    return path


class TestGuard:
    def test_warns_when_the_plugin_is_not_this_checkout(self, tmp_path: Path) -> None:
        project = _pyeye_repo(tmp_path / "worktree")
        installed = _pyeye_repo(tmp_path / "cache" / "pyeye" / "2.2.0")
        message = rt.guard_message(installed, project)
        assert message is not None
        assert str(installed) in message
        assert "--plugin-dir" in message

    def test_silent_when_the_plugin_is_this_checkout(self, tmp_path: Path) -> None:
        project = _pyeye_repo(tmp_path / "worktree")
        assert rt.guard_message(project, tmp_path / "worktree" / ".") is None

    def test_silent_outside_the_pyeye_repo(self, tmp_path: Path) -> None:
        (tmp_path / "other").mkdir()
        assert rt.guard_message(_pyeye_repo(tmp_path / "plugin"), tmp_path / "other") is None

    def test_silent_for_another_plugins_repo(self, tmp_path: Path) -> None:
        project = _pyeye_repo(tmp_path / "other", name="superpowers")
        assert rt.guard_message(_pyeye_repo(tmp_path / "plugin"), project) is None

    def test_guard_main_prints_hook_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(_pyeye_repo(tmp_path / "installed")))
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(_pyeye_repo(tmp_path / "wt")))
        assert rt.main(["guard"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert "--plugin-dir" in out["systemMessage"]
        assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert out["hookSpecificOutput"]["additionalContext"] == out["systemMessage"]

    def test_guard_main_is_silent_without_env(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        assert rt.main(["guard"]) == 0
        assert capsys.readouterr().out == ""


class TestMain:
    @pytest.fixture
    def env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
        root, data = _plugin_root(tmp_path / "root"), tmp_path / "data"
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
        return root, data

    def test_launch_syncs_then_execs_the_server(
        self, env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root, data = env
        uv, execs = FakeUv(), []
        monkeypatch.setattr(rt.subprocess, "run", uv)
        monkeypatch.setattr(rt, "_exec", lambda argv: execs.append(argv) or 0)
        assert rt.main(["launch", "--extra"]) == 0
        python = rt.venv_python(rt.slot_dir(root, data) / ".venv")
        assert execs == [[str(python), "-m", "pyeye.mcp", "--extra"]]

    def test_python_mode_runs_args_in_the_roots_venv(
        self, env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # How a shipped skill runs `python -m pyeye.decisions ...` (#1136).
        root, data = env
        execs: list[list[str]] = []
        monkeypatch.setattr(rt.subprocess, "run", FakeUv())
        monkeypatch.setattr(rt, "_exec", lambda argv: execs.append(argv) or 0)
        assert rt.main(["python", "-m", "pyeye.decisions", "index", "--active"]) == 0
        python = rt.venv_python(rt.slot_dir(root, data) / ".venv")
        assert execs == [[str(python), "-m", "pyeye.decisions", "index", "--active"]]

    @pytest.mark.usefixtures("env")
    def test_launch_keeps_sync_output_off_stdout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # stdout is the MCP stdio channel: uv's output must go to stderr.
        uv = FakeUv()
        seen = []
        monkeypatch.setattr(
            rt.subprocess, "run", lambda cmd, **kw: seen.append(kw["stdout"]) or uv(cmd, **kw)
        )
        monkeypatch.setattr(rt, "_exec", lambda _argv: 0)
        rt.main(["launch"])
        assert seen == [rt.sys.stderr]

    @pytest.mark.usefixtures("env")
    def test_launch_fails_cleanly_when_sync_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(rt.subprocess, "run", FakeUv(returncode=3))
        monkeypatch.setattr(rt, "_exec", lambda _argv: pytest.fail("must not exec"))
        assert rt.main(["launch"]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "exit 3" in captured.err

    @pytest.mark.usefixtures("env")
    def test_setup_exit_2_on_failure_rewakes_claude(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(rt.subprocess, "run", FakeUv(returncode=1))
        assert rt.main(["setup"]) == 2
        assert "pyeye plugin setup error" in capsys.readouterr().out

    def test_setup_syncs_and_prunes(
        self, env: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root, data = env
        uv = FakeUv()
        gone = _plugin_root(tmp_path / "gone")
        rt.ensure(gone, data, run=uv, out=io.StringIO())
        (gone / "uv.lock").unlink()
        gone.rmdir()
        monkeypatch.setattr(rt.subprocess, "run", uv)
        assert rt.main(["setup"]) == 0
        assert rt.slot_dir(root, data).is_dir()
        assert not rt.slot_dir(gone, data).exists()

    @pytest.mark.parametrize("mode", ["launch", "python", "setup"])
    def test_requires_plugin_env(
        self, mode: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
        assert rt.main([mode]) != 0
        captured = capsys.readouterr()
        assert "CLAUDE_PLUGIN_ROOT" in captured.out + captured.err

    def test_unknown_mode(self) -> None:
        assert rt.main(["bogus"]) == 2
