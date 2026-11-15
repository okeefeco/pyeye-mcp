"""Tests for the report-only duplicate-code check (#616).

Pins three things: renamed copies are caught (the reason for an AST check over
pylint's line-based ``duplicate-code``), unrelated code stays quiet, and the
check is NON-BLOCKING by default. Making it blocking is a pending user decision,
so the pre-commit hook must not pass ``--fail-on-findings``.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "duplicate_code_report.py"
_spec = importlib.util.spec_from_file_location("duplicate_code_report", _SCRIPT)
assert _spec and _spec.loader
dup = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = dup  # dataclasses resolve their module via sys.modules
_spec.loader.exec_module(dup)

_ORIGINAL = textwrap.dedent("""
    def find(handle, analyzer):
        parts = handle.split(".")
        module_dotted = ".".join(parts[:-1])
        leaf = parts[-1]
        try:
            script = analyzer.make_script(module_dotted, leaf)
            inferred = script.infer(2, len(module_dotted) + 1 + len(leaf))
            for n in inferred:
                if n.full_name == handle:
                    return n
        except Exception:
            pass
        return None
    """)

# Same logic, every local renamed, a docstring and comments added.
_RENAMED_COPY = textwrap.dedent('''
    def lookup(name, an):
        """Mirrors find() -- the kind of parity claim that drifts."""
        bits = name.split(".")
        mod = ".".join(bits[:-1])
        tail = bits[-1]
        try:
            s = an.make_script(mod, tail)  # copied at fix time
            got = s.infer(2, len(mod) + 1 + len(tail))
            for item in got:
                if item.full_name == name:
                    return item
        except Exception:
            pass
        return None
    ''')

_UNRELATED = textwrap.dedent("""
    class Cache:
        def __init__(self, size):
            self.size = size
            self.items = {}

        def put(self, key, value):
            if len(self.items) >= self.size:
                self.items.pop(next(iter(self.items)))
            self.items[key] = value
    """)


def _write(tmp_path: Path, **files: str) -> list[Path]:
    paths = []
    for name, body in files.items():
        p = tmp_path / f"{name}.py"
        p.write_text(body, encoding="utf-8")
        paths.append(p)
    return paths


def test_renamed_copy_across_files_is_reported(tmp_path: Path) -> None:
    paths = _write(tmp_path, original=_ORIGINAL, copy=_RENAMED_COPY)
    clones = dup.find_clones(dup.collect(paths, root=tmp_path), min_tokens=35)
    assert len(clones) == 1
    clone = clones[0]
    assert {clone.a_file, clone.b_file} == {"original.py", "copy.py"}
    assert clone.tokens >= 35


def test_unrelated_code_is_quiet(tmp_path: Path) -> None:
    paths = _write(tmp_path, original=_ORIGINAL, cache=_UNRELATED)
    assert dup.find_clones(dup.collect(paths, root=tmp_path), min_tokens=35) == []


def test_attribute_names_are_significant(tmp_path: Path) -> None:
    """Same shape, different API calls: not a copy."""
    other_api = _RENAMED_COPY.replace(".infer(", ".goto(").replace(".full_name", ".module_name")
    other_api = other_api.replace(".make_script(", ".build(").replace(".split(", ".partition(")
    paths = _write(tmp_path, original=_ORIGINAL, other=other_api)
    assert dup.find_clones(dup.collect(paths, root=tmp_path), min_tokens=35) == []


def test_copy_within_one_file_is_reported_once(tmp_path: Path) -> None:
    paths = _write(tmp_path, both=_ORIGINAL + "\n" + _RENAMED_COPY)
    clones = dup.find_clones(dup.collect(paths, root=tmp_path), min_tokens=35)
    assert len(clones) == 1
    assert clones[0].a_file == clones[0].b_file == "both.py"
    assert clones[0].a_end < clones[0].b_start


def test_nested_alignments_are_collapsed() -> None:
    outer = dup.Clone("a.py", 10, 30, "b.py", 50, 70, 60)
    inner = dup.Clone("a.py", 12, 30, "b.py", 52, 70, 50)
    elsewhere = dup.Clone("a.py", 100, 110, "b.py", 52, 70, 40)
    assert dup._drop_nested([outer, inner, elsewhere]) == [outer, elsewhere]


def test_cli_is_report_only_by_default(tmp_path: Path, capsys) -> None:
    paths = _write(tmp_path, original=_ORIGINAL, copy=_RENAMED_COPY)
    argv = [str(p) for p in paths] + ["--min-tokens", "35"]

    assert dup.main(argv) == 0
    out = capsys.readouterr().out
    assert "1 clone region(s)" in out
    assert "non-blocking" in out

    assert dup.main([*argv, "--fail-on-findings"]) == 1


def test_cli_clean_tree_exits_zero_even_when_strict(tmp_path: Path, capsys) -> None:
    paths = _write(tmp_path, cache=_UNRELATED)
    assert dup.main([str(p) for p in paths] + ["--fail-on-findings"]) == 0
    assert "0 clone region(s)" in capsys.readouterr().out


def test_default_targets_exist() -> None:
    for target in dup.DEFAULT_TARGETS:
        assert (_ROOT / target).exists(), target


def test_precommit_hook_is_non_blocking() -> None:
    """The hook must report, never fail: blocking is a pending user decision (#616)."""
    config = yaml.safe_load((_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = {h["id"]: h for repo in config["repos"] for h in repo["hooks"]}
    hook = hooks["duplicate-code-report"]
    assert "scripts/duplicate_code_report.py" in hook["entry"]
    assert "--fail-on-findings" not in hook["entry"]
    assert "--fail-on-findings" not in hook.get("args", [])
    assert hook.get("verbose") is True  # otherwise a passing hook's report is hidden
