"""Repository config facts: pre-commit hooks, CI's uv flags and the pyeye config (#830, C17)."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from pyeye import config as config_module
from pyeye.config import CONFIG_KEYS, IGNORED_TOP_LEVEL_KEYS, ProjectConfig
from pyeye.constants import CONFIG_FILES, GLOBAL_CONFIG_FILES, OVERRIDE_FILE
from pyeye.docs_facts import registry
from pyeye.docs_facts.extractors import ci, repo_config
from pyeye.docs_facts.facts import ExtractionError

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "pyeye"


@pytest.fixture(scope="module")
def facts() -> dict[str, Any]:
    return {f.id: f for f in repo_config.extract(ROOT)}


class TestPreCommitHooks:
    def test_hook_ids_are_read_in_file_order_once(self) -> None:
        text = """
repos:
  - repo: local
    hooks:
      - id: first
        name: First
      - id: second-hook
  - repo: https://example.invalid/x
    hooks:
      - id: first
"""
        assert repo_config.hook_ids(text) == ["first", "second-hook"]
        assert repo_config.hook_repos(text) == {"first": "local", "second-hook": "local"}

    def test_a_config_with_no_hooks_fails_loudly(self, tmp_path: Path) -> None:
        (tmp_path / repo_config.PRE_COMMIT_CONFIG).write_text("repos: []\n", encoding="utf-8")
        with pytest.raises(ExtractionError, match="no hook ids"):
            list(repo_config.extract(tmp_path))

    def test_the_repo_hooks_are_facts(self, facts: dict[str, Any]) -> None:
        text = (ROOT / repo_config.PRE_COMMIT_CONFIG).read_text(encoding="utf-8")
        ids = repo_config.hook_ids(text)
        assert {"docs-facts-generate", "detect-secrets", "bandit", "pip-audit"} <= set(ids)
        assert facts["precommit.hooks"].members == tuple(f"precommit.hook.{i}" for i in ids)
        assert facts["precommit.hook.docs-facts-generate"].value == {"repo": "local"}
        assert facts["precommit.hook.markdownlint"].value["repo"].startswith("https://")


class TestUvRunFlags:
    def test_the_flags_every_uv_run_hook_shares(self) -> None:
        text = "      entry: uv run --frozen black\n      entry: uv run --frozen --no-sync ruff\n"
        assert repo_config.uv_run_flags(text) == ["--frozen"]

    def test_a_hook_without_them_or_no_hook_fails(self) -> None:
        with pytest.raises(ExtractionError, match="share no flag"):
            repo_config.uv_run_flags("entry: uv run --frozen a\nentry: uv run b\n")
        with pytest.raises(ExtractionError, match="no `uv run`"):
            repo_config.uv_run_flags("entry: npx markdownlint\n")

    def test_the_repo_fact(self, facts: dict[str, Any]) -> None:
        assert facts["precommit.uv_run_flags"].value == ["--frozen"]


class TestConfigNames:
    def test_keys_ignored_keys_and_files_come_from_the_constants(
        self, facts: dict[str, Any]
    ) -> None:
        assert [facts[m].value for m in facts["config.keys"].members] == list(CONFIG_KEYS)
        assert [facts[m].value for m in facts["config.ignored_keys"].members] == list(
            IGNORED_TOP_LEVEL_KEYS
        )
        assert facts["config.files.project"].value == list(CONFIG_FILES)
        assert facts["config.files.global"].value == list(GLOBAL_CONFIG_FILES)
        assert facts["config.files.override"].value == OVERRIDE_FILE

    def test_no_key_is_both_read_and_ignored(self) -> None:
        assert not set(CONFIG_KEYS) & set(IGNORED_TOP_LEVEL_KEYS)

    def test_config_keys_are_exactly_the_top_level_keys_code_reads(self) -> None:
        """A fitness check: the CONFIG_KEYS fact can't fall behind the code that reads keys."""
        owners = {"self.config", "config.config", "self.config.config", "project_config.config"}
        read: set[str] = set()
        for path in SRC.rglob("*.py"):
            if "docs_facts" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                target: ast.expr | None = None
                key: object = None
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("get", "setdefault")
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                ):
                    target, key = node.func.value, node.args[0].value
                elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
                    target, key = node.value, node.slice.value
                if target is not None and isinstance(key, str) and ast.unparse(target) in owners:
                    read.add(key)
        assert read == set(CONFIG_KEYS)

    def test_global_config_files_are_still_tried_in_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        (home / ".config" / "pyeye").mkdir(parents=True)
        (home / ".config" / "pyeye" / "config.json").write_text(
            '{"packages": ["first"]}', encoding="utf-8"
        )
        (home / ".pyeye.json").write_text('{"packages": ["second"]}', encoding="utf-8")
        monkeypatch.setattr(config_module.Path, "home", lambda: home)
        project = tmp_path / "project"
        project.mkdir()

        assert ProjectConfig(project.as_posix()).config["packages"] == ["first"]


class TestUvSyncFlags:
    def test_the_flags_every_sync_shares(self) -> None:
        workflow = (
            "run: uv sync --locked --group docs\n"
            "run: uv sync --locked  # comment\n"
            "run: uv sync --locked\n"
        )
        assert ci._uv_sync_flags(workflow).value == ["--locked"]

    def test_a_sync_without_the_shared_flags_fails(self) -> None:
        with pytest.raises(ExtractionError, match="share no flag"):
            ci._uv_sync_flags("run: uv sync --locked\nrun: uv sync\n")
        with pytest.raises(ExtractionError, match="no `uv sync`"):
            ci._uv_sync_flags("run: uv run pytest\n")

    def test_the_repo_fact(self) -> None:
        fact = {f.id: f for f in ci.extract(ROOT)}["ci.uv_sync_flags"]
        assert fact.value == ["--locked"] and fact.markdown == "`--locked`"


def test_the_families_are_registered() -> None:
    prefixes = {p for e in registry.EXTRACTORS for p in e.prefixes}
    assert {"precommit", "config"} <= prefixes
