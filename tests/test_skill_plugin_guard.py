"""A shipped skill's plugin command fails with a hint outside the plugin (#1131).

Claude Code substitutes ``${CLAUDE_PLUGIN_ROOT}`` / ``${CLAUDE_PLUGIN_DATA}``
into a plugin skill's text when it loads it; the variables are NOT in the
environment of Bash tool commands. A command copied out of that context (the
skill read from the repo, pasted elsewhere) used to run with both empty and
fail as ``/.venv: Permission denied``. Each command now checks the substituted
values first and prints what to do instead.

Only the plain ``${NAME}`` form is documented as substituted, so a shell
parameter-expansion form (``${CLAUDE_PLUGIN_ROOT:?hint}``) would be left as is
and fail even when loaded through the plugin: it is never used.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pyeye.docs_facts.docs import DOCS

ROOT = Path(__file__).resolve().parent.parent
_PLUGIN_VARS = ("CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA")
# Every registered skill page that uses the plugin variables: a new one is
# checked without being listed here.
SKILLS = {
    entry.path: ROOT / entry.path
    for entry in DOCS
    if entry.kind == "skill"
    and "${CLAUDE_PLUGIN_" in (ROOT / entry.path).read_text(encoding="utf-8")
}
_BLOCK = re.compile(r"```bash\n(.*?)```", re.DOTALL)

needs_bash = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None, reason="runs the snippet in POSIX bash"
)


def _plugin_command(skill: str) -> str:
    """The skill's one bash block that uses the plugin variables."""
    blocks = [
        b
        for b in _BLOCK.findall(SKILLS[skill].read_text(encoding="utf-8"))
        if "${CLAUDE_PLUGIN_" in b
    ]
    assert len(blocks) == 1, blocks
    return blocks[0]


def _run(snippet: str, tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run *snippet* with a fake ``uv`` first on PATH; return the result and its log."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "uv.log"
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        f'#!/bin/sh\necho "env=$UV_PROJECT_ENVIRONMENT args=$*" > "{log.as_posix()}"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in _PLUGIN_VARS}
    env["PATH"] = f"{bin_dir.as_posix()}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(  # noqa: S603 - fixed argv, our own snippet
        ["bash", "-c", snippet],  # noqa: S607
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return result, log


def test_the_skills_that_use_them_are_found() -> None:
    assert {"skills/decision-log/SKILL.md", "skills/duplication-review/SKILL.md"} <= set(SKILLS)


@pytest.mark.parametrize("skill", sorted(SKILLS))
class TestThePluginCommand:
    def test_only_the_plain_form_is_used(self, skill: str) -> None:
        """``${VAR:?…}`` / ``${VAR:-…}`` aren't substituted by Claude Code."""
        text = SKILLS[skill].read_text(encoding="utf-8")
        assert not re.search(r"\$\{CLAUDE_PLUGIN_[A-Z_]+[:#%/]", text)
        assert '"${CLAUDE_PLUGIN_ROOT}"' in text
        assert '"${CLAUDE_PLUGIN_DATA}/.venv"' in text

    @needs_bash
    def test_unsubstituted_it_fails_with_a_hint(self, skill: str, tmp_path: Path) -> None:
        result, log = _run(_plugin_command(skill), tmp_path)

        assert result.returncode != 0
        assert "pyeye plugin" in result.stderr
        assert "pyeye-mcp installed" in result.stderr
        assert not log.exists()  # uv never ran

    @needs_bash
    def test_substituted_it_runs_uv_in_the_plugin(self, skill: str, tmp_path: Path) -> None:
        plugin_root = tmp_path / "plugin"
        plugin_data = tmp_path / "data"
        snippet = (
            _plugin_command(skill)
            .replace("${CLAUDE_PLUGIN_ROOT}", plugin_root.as_posix())
            .replace("${CLAUDE_PLUGIN_DATA}", plugin_data.as_posix())
        )

        result, log = _run(snippet, tmp_path)

        assert result.returncode == 0, result.stderr
        recorded = log.read_text(encoding="utf-8")
        assert f"env={plugin_data.as_posix()}/.venv " in recorded
        assert f"--project {plugin_root.as_posix()} " in recorded
