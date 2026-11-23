"""The decision-log tooling ships in the package as ``pyeye.decisions`` (#1093).

``scripts/decisions.py`` existed only in this repository, so every other repo
using the plugin's ``decision-log`` skill got its instructions without its
tooling. The engine now lives in ``pyeye.decisions`` (``python -m
pyeye.decisions index|check|migrate``): stdlib only, its directory and
grandfather list configurable, defaulting to ``./docs/decisions`` and none.
``scripts/decisions.py`` is a thin wrapper that loads it by file path (CI runs
it with a bare ``python``, where importing the ``pyeye`` package would need
``parso``) and passes this repo's grandfather list and header.
"""

from __future__ import annotations

import ast
import subprocess  # nosec B404 - runs the repo's own script and module
import sys
from pathlib import Path

import pytest

from pyeye import decisions

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "decisions.py"
MODULE = ROOT / "src" / "pyeye" / "decisions.py"
SKILL = ROOT / ".claude" / "skills" / "decision-log" / "SKILL.md"


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 - fixed argv
        # The module writes UTF-8 (titles carry — and …); decode it as UTF-8 on
        # every platform, not the locale's code page (cp1252 on Windows).
        argv,
        capture_output=True,
        encoding="utf-8",
        cwd=cwd,
        timeout=120,
        check=False,
    )


def _module(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return _run([sys.executable, "-m", "pyeye.decisions", *args], cwd)


class TestARepoWithNoDecisions:
    @pytest.mark.parametrize("command", ["index", "check"])
    def test_it_reports_no_entries_cleanly(self, tmp_path: Path, command: str) -> None:
        result = _module([command], tmp_path)

        assert result.returncode == 0, result.stderr
        assert "no entries" in result.stdout
        assert "Traceback" not in result.stderr


class TestTheModuleDefaults:
    def test_it_reads_docs_decisions_under_the_working_directory(self, tmp_path: Path) -> None:
        entries = tmp_path / "docs" / "decisions" / "entries"
        entries.mkdir(parents=True)
        meta = {
            "date": "2026-01-02",
            "title": "A decision (#1)",
            "issues": [1],
            "anchors": ["pkg.mod.f"],
            "status": "active",
            "amends": [],
            "supersedes": [],
            "amended_by": [],
            "superseded_by": [],
        }
        body = "## 2026-01-02 — A decision (#1)\n\n**Applies-to:** `pkg.mod.f`\n"
        (entries / "2026-01-02-1-a-decision.md").write_text(
            decisions.render(meta, body), encoding="utf-8", newline="\n"
        )

        result = _module(["check"], tmp_path)

        assert result.returncode == 0, result.stderr
        assert "1 entries OK" in result.stdout

    def test_nothing_is_grandfathered_by_default(self) -> None:
        """This repo's grandfather list is the wrapper's, not every user's."""
        assert frozenset() == decisions.DEFAULT_GRANDFATHERED
        meta = {
            "date": "2026-01-02",
            "title": "No applies-to (#1)",
            "issues": [1],
            "anchors": ["pkg.f"],
            "status": "active",
            "amends": [],
            "supersedes": [],
            "amended_by": [],
            "superseded_by": [],
        }
        entry = decisions.parse(
            "2026-01-02-1-no-applies-to.md",
            decisions.render(meta, "## 2026-01-02 — No applies-to (#1)\n\nbody\n"),
        )

        assert any("Applies-to" in p for p in decisions.check([entry]))

    def test_the_grandfather_list_is_configurable(self, tmp_path: Path) -> None:
        entries = tmp_path / "docs" / "decisions" / "entries"
        entries.mkdir(parents=True)
        meta = {
            "date": "2026-01-02",
            "title": "Old (#1)",
            "issues": [1],
            "anchors": ["pkg.f"],
            "status": "active",
            "amends": [],
            "supersedes": [],
            "amended_by": [],
            "superseded_by": [],
        }
        name = "2026-01-02-1-old.md"
        (entries / name).write_text(
            decisions.render(meta, "## 2026-01-02 — Old (#1)\n\nbody\n"),
            encoding="utf-8",
            newline="\n",
        )

        assert _module(["check"], tmp_path).returncode == 1
        assert _module(["--grandfathered", name, "check"], tmp_path).returncode == 0

    def test_the_directory_is_configurable(self, tmp_path: Path) -> None:
        (tmp_path / "elsewhere" / "entries").mkdir(parents=True)
        result = _module(["--decisions-dir", "elsewhere", "check"], tmp_path)

        assert result.returncode == 0, result.stderr
        assert "no entries" in result.stdout


class TestTheShippedHeader:
    """The header ``migrate`` writes in any repo names the skill, not a path in this one (#1177)."""

    def test_it_names_no_repo_relative_skill_path(self) -> None:
        """``skills/decision-log/SKILL.md`` moved (#1153); elsewhere it comes from the plugin."""
        assert "SKILL.md" not in decisions.STATIC_HEADER
        assert "skills/" not in decisions.STATIC_HEADER

    def test_it_still_names_the_skill(self) -> None:
        assert "`decision-log` skill" in decisions.STATIC_HEADER

    def test_this_repos_log_is_the_wrappers_header(self) -> None:
        """This repo's ``DECISIONS.md`` is the wrapper's header, which ``check`` enforces."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("decisions_wrapper_header", WRAPPER)
        assert spec is not None and spec.loader is not None
        wrapper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wrapper)
        assert (ROOT / "docs" / "decisions" / "DECISIONS.md").read_text(
            encoding="utf-8"
        ) == wrapper.STATIC_HEADER


class TestTheRepoWrapper:
    @pytest.mark.parametrize(
        "args",
        [["check"], ["index"], ["index", "--active"], ["index", "--symbol", "resolve_handle"]],
    )
    def test_it_answers_as_the_module_does_with_this_repos_settings(
        self, args: list[str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The regression guard: the wrapper is the module plus this repo's config."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("decisions_wrapper", WRAPPER)
        assert spec is not None and spec.loader is not None
        wrapper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wrapper)
        through_wrapper = _run([sys.executable, str(WRAPPER), *args], ROOT)

        code = decisions.main(
            args,
            decisions_dir=ROOT / "docs" / "decisions",
            grandfathered=wrapper.APPLIES_TO_GRANDFATHERED,
            header=wrapper.STATIC_HEADER,
            command=wrapper.COMMAND,
        )

        assert through_wrapper.returncode == code == 0
        assert through_wrapper.stdout == capsys.readouterr().out

    def test_it_runs_with_a_bare_python(self) -> None:
        """CI runs it with no project installed: no site-packages, no parso (-I -S)."""
        result = _run([sys.executable, "-I", "-S", str(WRAPPER), "check"], ROOT)

        assert result.returncode == 0, result.stderr
        assert "entries OK" in result.stdout

    def test_the_module_imports_only_the_standard_library(self) -> None:
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
        }
        assert not any(isinstance(n, ast.ImportFrom) and n.level for n in ast.walk(tree))
        assert imported <= set(sys.stdlib_module_names) | {"__future__"}, imported


class TestTheSkill:
    def test_it_runs_the_shipped_module_through_the_plugin(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        assert '"${CLAUDE_PLUGIN_ROOT}/scripts/plugin_runtime.py"' in text  # #1136
        assert "python -m pyeye.decisions index --active" in text
        assert "python -m pyeye.decisions check" in text
        assert "scripts/decisions.py" not in text  # other repos don't have it

    def test_every_documented_subcommand_and_flag_exists(self) -> None:
        import re

        text = SKILL.read_text(encoding="utf-8")
        for command in set(re.findall(r"python -m pyeye\.decisions (\w+)", text)):
            assert command in {"index", "check", "migrate"}, command
        parser_help = _module(["index", "--help"], ROOT).stdout
        for flag in set(re.findall(r"`(--[a-z][a-z-]*)", text)):
            assert flag in parser_help or flag in _module(["--help"], ROOT).stdout, flag
