"""Regression tests for how the pyeye MCP server is launched (#600, #1136, #1147).

#600: the server was started with ``uv run --no-sync`` against an empty venv, so
``python -m pyeye.mcp`` exited with ``No module named 'pyeye'`` and Claude Code
showed ``CONNECTION_CLOSED`` for the whole session.  The rule still holds:
nothing may start the server against a venv that nobody filled.

#1136: the plugin's venv is keyed on the plugin ROOT, not on
``${CLAUDE_PLUGIN_DATA}`` alone (every ``--plugin-dir`` session is
``pyeye@inline`` and shares one data dir), and the launcher syncs it
synchronously when it is missing or stale.

#1147: in pyeye's own repository every session runs its worktree's code without
``--plugin-dir``.  The repo-root ``.mcp.json`` is back and targets the session's
project; the shipped skills live in ``.claude/skills/`` (project skills here),
``plugin.json`` publishes exactly those four, and the project settings turn the
installed plugin off and the ``.mcp.json`` server on.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404 — launches uv/git/bash with fixed argument lists
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_MCP_JSON = _REPO / ".mcp.json"
_PLUGIN_JSON = _REPO / ".claude-plugin" / "plugin.json"
_PLUGIN_HOOKS = _REPO / "hooks" / "hooks.json"
_SETTINGS = _REPO / ".claude" / "settings.json"
_RUNTIME = "${CLAUDE_PLUGIN_ROOT}/scripts/plugin_runtime.py"
SHIPPED_SKILLS = ("architecture-review", "decision-log", "duplication-review", "python-explore")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _server(config: Path = _PLUGIN_JSON) -> dict:
    return _load(config)["mcpServers"]["pyeye"]


def _session_start_commands() -> list[str]:
    hooks = _load(_PLUGIN_HOOKS)["hooks"]
    return [h["command"] for entry in hooks["SessionStart"] for h in entry["hooks"]]


class TestRepoMcpJson:
    """The repo's own server: each worktree's session runs its own checkout (#1147)."""

    def test_runs_pyeye_through_uv(self) -> None:
        server = _server(_MCP_JSON)
        assert server["command"] == "uv"
        assert server["args"][0] == "run"
        assert server["args"][-3:] == ["python", "-m", "pyeye.mcp"]

    def test_targets_the_session_project(self) -> None:
        args = _server(_MCP_JSON)["args"]
        assert args[args.index("--project") + 1] == "${CLAUDE_PROJECT_DIR:-.}"

    def test_syncs_frozen_rather_than_no_sync(self) -> None:
        args = _server(_MCP_JSON)["args"]
        assert "--no-sync" not in args, (
            "nothing fills a new worktree's venv before the server starts, so "
            "--no-sync leaves it empty and the server cannot import pyeye (#600)"
        )
        assert "--frozen" in args, "install exactly uv.lock without re-resolving it"
        assert "--locked" not in args, "--locked is for CI only"


class TestProjectSettings:
    def test_turns_the_installed_plugin_off_here(self) -> None:
        # Otherwise every tool and skill appears twice (plugin + project).
        assert _load(_SETTINGS)["enabledPlugins"] == {"pyeye@pyeye-marketplace": False}

    def test_enables_the_mcp_json_server(self) -> None:
        assert _load(_SETTINGS)["enabledMcpjsonServers"] == ["pyeye"]


class TestPluginServer:
    def test_launches_through_the_runtime_script(self) -> None:
        server = _server()
        assert server["command"] == "uv"
        assert server["args"][:3] == ["run", "--no-project", "python"]
        assert server["args"][3:] == [_RUNTIME, "launch"]

    def test_has_no_shared_venv(self) -> None:
        # A fixed UV_PROJECT_ENVIRONMENT is shared by every --plugin-dir checkout.
        assert "UV_PROJECT_ENVIRONMENT" not in _server().get("env", {})
        assert "--no-sync" not in _server()["args"], "#600: nothing fills it first"


class TestPluginSkills:
    def test_publishes_exactly_the_four_shipped_skills(self) -> None:
        # Listed by path, so the repo-internal skills beside them never ship.
        expected = [f"./.claude/skills/{name}/" for name in SHIPPED_SKILLS]
        assert _load(_PLUGIN_JSON)["skills"] == expected

    @pytest.mark.parametrize("name", SHIPPED_SKILLS)
    def test_each_listed_skill_exists(self, name: str) -> None:
        assert (_REPO / ".claude" / "skills" / name / "SKILL.md").is_file()

    def test_no_top_level_skills_dir(self) -> None:
        # Claude Code would also load a plugin's default skills/ directory.
        assert not (_REPO / "skills").exists()


class TestSessionStartHooks:
    def test_only_the_setup_hook(self) -> None:
        assert _session_start_commands() == [f'uv run --no-project python "{_RUNTIME}" setup']

    def test_old_setup_script_is_gone(self) -> None:
        assert not (_REPO / "scripts" / "install_plugin_deps.py").exists()


def _runner_blocks(text: str) -> list[str]:
    """The ```bash blocks of *text* that run a pyeye module."""
    blocks = text.split("```bash\n")[1:]
    return [b.split("```")[0] for b in blocks if "python -m pyeye." in b]


def test_shipped_skills_run_pyeye_as_plugin_or_project_skill() -> None:
    # As a plugin skill ${CLAUDE_PLUGIN_ROOT} is substituted; as a project skill
    # (pyeye's own repo) it isn't, so it expands empty and needs the fallback.
    for name in SHIPPED_SKILLS:
        text = (_REPO / ".claude" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert "CLAUDE_PLUGIN_DATA}/.venv" not in text, name
        for block in _runner_blocks(text):
            assert block.startswith('if [ -n "${CLAUDE_PLUGIN_ROOT}" ]; then'), name
            assert f'"{_RUNTIME}" \\\n    python -m pyeye.' in block, name
            assert 'uv run --project "$(git rev-parse --show-toplevel)" --frozen' in block, name


# --- integration: a real sync into fresh worktrees ---------------------------


def _clean_env(data: Path, root: Path) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")
    }
    env["CLAUDE_PLUGIN_ROOT"] = str(root)
    env["CLAUDE_PLUGIN_DATA"] = str(data)
    return env


@pytest.mark.slow
@pytest.mark.integration
class TestFreshWorktrees:
    """Run the real runtime against brand-new worktrees with no venv."""

    @pytest.fixture
    def make_worktree(self, tmp_path: Path):
        uv, git = shutil.which("uv"), shutil.which("git")
        if not uv or not git:
            pytest.skip("needs uv and git on PATH")
        if not (_REPO / ".git").exists():
            pytest.skip("needs a git checkout (setuptools-scm reads the version from git)")
        # Hooks off (an empty hooks dir, portable to Git for Windows): the repo's
        # post-checkout hook can create a .venv, hiding the cold-start case.
        no_hooks = tmp_path / "no-hooks"
        no_hooks.mkdir()
        made: list[Path] = []

        def make(name: str) -> Path:
            worktree = tmp_path / name
            subprocess.run(  # nosec B603
                [git, "-c", f"core.hooksPath={no_hooks.as_posix()}", "-C", str(_REPO)]
                + ["worktree", "add", "--detach", str(worktree), "HEAD"],
                check=True,
                capture_output=True,
            )
            made.append(worktree)
            # The runtime is the working tree's, which may be uncommitted.
            shutil.copy2(_REPO / "scripts" / "plugin_runtime.py", worktree / "scripts")
            assert not (worktree / ".venv").exists()
            return worktree

        yield uv, make
        for worktree in made:
            # This test's own scratch worktrees: remove them, and if git refuses,
            # delete the directory and prune the stale registration.
            removed = subprocess.run(  # nosec B603
                [git, "-C", str(_REPO), "worktree", "remove", str(worktree)],
                capture_output=True,
            )
            if removed.returncode != 0:
                shutil.rmtree(worktree, ignore_errors=True)
                subprocess.run(  # nosec B603
                    [git, "-C", str(_REPO), "worktree", "prune"], capture_output=True
                )

    def _setup(self, uv: str, root: Path, data: Path) -> None:
        result = subprocess.run(  # nosec B603
            [uv, "run", "--no-project", "python", str(root / "scripts" / "plugin_runtime.py")]
            + ["setup"],
            capture_output=True,
            text=True,
            timeout=300,
            env=_clean_env(data, root),
        )
        assert result.returncode == 0, (result.stdout + result.stderr)[-2000:]

    def _imported_from(self, uv: str, data: Path, root: Path) -> Path:
        # Through the runtime's `python` mode, as a shipped skill runs pyeye.
        result = subprocess.run(  # nosec B603
            [uv, "run", "--no-project", "python", str(root / "scripts" / "plugin_runtime.py")]
            + ["python", "-c", "import pyeye.mcp.server, pyeye; print(pyeye.__file__)"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(data),
            env=_clean_env(data, root),
        )
        assert result.returncode == 0, result.stderr[-2000:]
        return Path(result.stdout.strip())

    def test_two_checkouts_each_import_their_own_code(self, make_worktree, tmp_path) -> None:
        uv, make = make_worktree
        data = tmp_path / "plugin-data"  # ONE data dir, as pyeye@inline has
        a, b = make("wt-a"), make("wt-b")
        lock_before = (a / "uv.lock").read_bytes()
        self._setup(uv, a, data)
        self._setup(uv, b, data)
        assert self._imported_from(uv, data, a).is_relative_to(a / "src")
        assert self._imported_from(uv, data, b).is_relative_to(b / "src")
        assert (a / "uv.lock").read_bytes() == lock_before, "--frozen must not rewrite uv.lock"
        assert not (a / ".venv").exists(), "the checkout's own dev venv is never touched"


@pytest.mark.slow
@pytest.mark.integration
def test_a_cache_install_without_git_syncs_and_imports(tmp_path: Path) -> None:
    """#1148: Claude Code runs an installed plugin from a per-version cache copy
    with no ``.git``, where setuptools-scm finds no version and the build fails."""
    uv, git = shutil.which("uv"), shutil.which("git")
    if not uv or not git:
        pytest.skip("needs uv and git on PATH")
    if not (_REPO / ".git").exists():
        pytest.skip("needs a git checkout to export from")
    # As the plugin cache holds it: the tracked files, named by a short sha.
    root = tmp_path / "cache" / "pyeye-marketplace" / "pyeye" / "0123456789ab"
    root.mkdir(parents=True)
    archive = tmp_path / "plugin.tar"
    subprocess.run(  # nosec B603
        [git, "-C", str(_REPO), "archive", "--output", str(archive), "HEAD"], check=True
    )
    shutil.unpack_archive(archive, root)
    shutil.copy2(_REPO / "scripts" / "plugin_runtime.py", root / "scripts")
    assert not (root / ".git").exists()
    assert not (root / "src" / "pyeye" / "_version.py").exists()

    data = tmp_path / "data"
    env = _clean_env(data, root)
    env.pop("SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PYEYE_MCP", None)
    env.pop("SETUPTOOLS_SCM_PRETEND_VERSION", None)
    runtime = [uv, "run", "--no-project", "python", str(root / "scripts" / "plugin_runtime.py")]
    setup = subprocess.run(  # nosec B603
        [*runtime, "setup"], capture_output=True, text=True, timeout=300, env=env
    )
    assert setup.returncode == 0, (setup.stdout + setup.stderr)[-2000:]

    probe = "import pyeye, pyeye.mcp.server; print(pyeye.__version__); print(pyeye.__file__)"
    result = subprocess.run(  # nosec B603
        [*runtime, "python", "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(data),
    )
    assert result.returncode == 0, result.stderr[-2000:]
    version, module = result.stdout.split()
    assert version.endswith("+g0123456789ab"), version
    assert not version.startswith("0"), "the last release from CHANGELOG.md"
    assert Path(module).is_relative_to(root / "src")


@pytest.mark.slow
@pytest.mark.integration
class TestFreshWorktreeSkillsAndServer:
    """In a brand-new worktree with no venv (#600, #1147)."""

    @pytest.fixture
    def worktree(self, tmp_path: Path):
        git = shutil.which("git")
        if not shutil.which("uv") or not git or not shutil.which("bash"):
            pytest.skip("needs uv, git and bash on PATH")
        if not (_REPO / ".git").exists():
            pytest.skip("needs a git checkout (setuptools-scm reads the version from git)")
        no_hooks = tmp_path / "no-hooks"
        no_hooks.mkdir()
        worktree = tmp_path / "wt"
        subprocess.run(  # nosec B603
            [git, "-c", f"core.hooksPath={no_hooks.as_posix()}", "-C", str(_REPO)]
            + ["worktree", "add", "--detach", str(worktree), "HEAD"],
            check=True,
            capture_output=True,
        )
        # The runtime and skills are the working tree's, which may be uncommitted.
        shutil.copy2(_REPO / "scripts" / "plugin_runtime.py", worktree / "scripts")
        assert not (worktree / ".venv").exists()
        try:
            yield worktree
        finally:
            removed = subprocess.run(  # nosec B603
                [git, "-C", str(_REPO), "worktree", "remove", str(worktree)], capture_output=True
            )
            if removed.returncode != 0:
                shutil.rmtree(worktree, ignore_errors=True)
                subprocess.run(  # nosec B603
                    [git, "-C", str(_REPO), "worktree", "prune"], capture_output=True
                )

    @staticmethod
    def _env() -> dict[str, str]:
        drop = ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA")
        return {k: v for k, v in os.environ.items() if k not in drop}

    def test_mcp_json_server_imports_on_first_start(self, worktree: Path) -> None:
        args = _server(_MCP_JSON)["args"]
        # Same launch arguments, but import the server module instead of
        # starting it (a started server would wait on stdin).
        launch = [a.replace("${CLAUDE_PROJECT_DIR:-.}", str(worktree)) for a in args[:-2]]
        lock_before = (worktree / "uv.lock").read_bytes()
        result = subprocess.run(  # nosec B603
            [shutil.which("uv") or "uv", *launch, "-c", "import pyeye.mcp.server; print('ok')"],
            capture_output=True,
            text=True,
            timeout=300,
            env=self._env(),
        )
        assert result.returncode == 0, result.stderr[-2000:]
        assert "ok" in result.stdout
        assert (worktree / "uv.lock").read_bytes() == lock_before, "--frozen must not rewrite it"

    @pytest.mark.parametrize("mode", ["plugin", "project"])
    def test_decision_log_runner_works_both_ways(
        self, mode: str, worktree: Path, tmp_path: Path
    ) -> None:
        text = (_REPO / ".claude" / "skills" / "decision-log" / "SKILL.md").read_text("utf-8")
        [block] = _runner_blocks(text)
        env = self._env()
        if mode == "plugin":
            # Claude Code substitutes the tokens in a plugin skill's text.
            block = block.replace("${CLAUDE_PLUGIN_ROOT}", str(worktree))
            block = block.replace("${CLAUDE_PLUGIN_DATA}", str(tmp_path / "data"))
        # As a project skill nothing is substituted, and the variables are unset.
        result = subprocess.run(  # nosec B603
            [shutil.which("bash") or "bash", "-c", block],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(worktree),
            env=env,
        )
        assert result.returncode == 0, (result.stdout + result.stderr)[-2000:]
        assert "#1136" in result.stdout, "the index lists this repo's entries"
        venv_made = (worktree / ".venv").exists()
        assert venv_made == (mode == "project"), "plugin mode uses the plugin's venv"
