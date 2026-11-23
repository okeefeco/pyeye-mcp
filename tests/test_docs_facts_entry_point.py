"""``python -m pyeye.docs_facts``: the shipped entry point (#1162).

A skill runs docs-facts on a user's repository through the plugin's
environment, so the package must ship a runnable module, not only pyeye's
``scripts/docs_facts.py``. The module and the script run the same
:func:`pyeye.docs_facts.cli.main` and must say exactly the same thing.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - runs this interpreter with fixed arguments
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "docs_facts_inline"
DEV_DOC = ROOT / "docs" / "development" / "docs-facts.md"
PLUGIN_COMMAND = (
    'uv run --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/plugin_runtime.py" '
    "python -m pyeye.docs_facts"
)


def _run(args: list[str], cwd: Path) -> tuple[int, str, str]:
    done = subprocess.run(  # nosec B603 - fixed arguments, this interpreter
        [sys.executable, *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    return done.returncode, done.stdout, done.stderr


def _module(args: list[str], cwd: Path) -> tuple[int, str, str]:
    return _run(["-m", "pyeye.docs_facts", *args], cwd)


def _script(args: list[str], cwd: Path) -> tuple[int, str, str]:
    return _run([(ROOT / "scripts" / "docs_facts.py").as_posix(), *args], cwd)


class TestTheModuleIsTheScript:
    @pytest.mark.parametrize(
        "args",
        [
            ["check"],
            ["check", "--root", FIXTURE.as_posix()],
            ["--help"],
            ["bogus"],
        ],
        ids=["check-pyeye", "check-fixture", "help", "bad-command"],
    )
    def test_same_exit_code_and_output(self, args: list[str]) -> None:
        module = _module(args, ROOT)
        assert module == _script(args, ROOT)
        assert module[0] == (2 if args == ["bogus"] else 0)

    def test_the_working_directory_is_the_repository(self) -> None:
        """Run from inside a repository, the module needs no ``--root``."""
        assert _module(["check"], FIXTURE) == _module(["check", "--root", "."], FIXTURE)
        assert _module(["check"], FIXTURE)[0] == 0


class TestOnAUsersRepository:
    def test_no_config_is_nothing_to_check(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
        code, out, err = _module(["check"], tmp_path)
        assert (code, out) == (1, "")
        assert "nothing to check" in err

    def test_generate_then_check_on_an_inline_config(self, tmp_path: Path) -> None:
        repo = Path(shutil.copytree(FIXTURE, tmp_path / "repo"))
        settings = repo / "app" / "settings.py"
        settings.write_text(
            settings.read_text(encoding="utf-8").replace("TIMEOUT = 30", "TIMEOUT = 45"),
            encoding="utf-8",
        )
        assert _module(["check"], repo)[0] == 1
        assert _module(["generate"], repo)[0] == 0
        assert _module(["check"], repo)[0] == 0
        assert "`45`" in (repo / "docs" / "overview.md").read_text(encoding="utf-8")


def test_the_dev_doc_gives_the_plugin_command() -> None:
    """How a skill runs it through the plugin's environment (``plugin_runtime.py python``)."""
    assert PLUGIN_COMMAND in DEV_DOC.read_text(encoding="utf-8")
