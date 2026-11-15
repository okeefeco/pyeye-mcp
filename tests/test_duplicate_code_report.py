"""Tests for the duplicate-code ratchet (#616, made blocking in #636).

Pins: renamed copies are caught (the reason for an AST check over pylint's
line-based ``duplicate-code``), unrelated code stays quiet, clone regions are
keyed by their enclosing functions (not line numbers), and the baseline is an
exact ratchet like the #614/#615 fitness tests: a new clone fails, and a
baselined clone that has gone fails until its entry is deleted.
"""

from __future__ import annotations

import importlib.util
import re
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


def test_cli_report_only_never_fails(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(dup, "BASELINE", {})
    paths = _write(tmp_path, original=_ORIGINAL, copy=_RENAMED_COPY)
    argv = [str(p) for p in paths] + ["--min-tokens", "35", "--root", str(tmp_path)]
    assert dup.main([*argv, "--report-only"]) == 0
    assert "1 clone region(s)" in capsys.readouterr().out


def test_cli_fail_on_findings_ignores_the_baseline(tmp_path: Path, monkeypatch) -> None:
    """Strictest mode: any clone fails, baselined or not."""
    paths = _write(tmp_path, original=_ORIGINAL, copy=_RENAMED_COPY)
    argv = [str(p) for p in paths] + ["--min-tokens", "35", "--root", str(tmp_path)]
    monkeypatch.setattr(dup, "BASELINE", {("copy.py::lookup", "original.py::find"): "#1"})
    assert dup.main(argv) == 0  # baselined: the ratchet passes
    assert dup.main([*argv, "--fail-on-findings"]) == 1


def test_cli_clean_tree_exits_zero_even_when_strict(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(dup, "BASELINE", {})
    paths = _write(tmp_path, cache=_UNRELATED)
    argv = [str(p) for p in paths] + ["--root", str(tmp_path)]
    assert dup.main([*argv, "--fail-on-findings"]) == 0
    assert "0 clone region(s)" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The ratchet (#636)
# ---------------------------------------------------------------------------

_NESTED = textwrap.dedent("""
    X = 1


    class Outer:
        def method(self):
            def inner():
                return 1

            return inner()


    def top():
        return 2
    """)


def test_enclosing_qualname(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(_NESTED, encoding="utf-8")
    lines = _NESTED.splitlines()
    line_of = {text.strip(): n for n, text in enumerate(lines, start=1)}
    assert dup.enclosing("m.py", line_of["X = 1"], tmp_path) == "<module>"
    assert dup.enclosing("m.py", line_of["return inner()"], tmp_path) == "Outer.method"
    assert dup.enclosing("m.py", line_of["return 1"], tmp_path) == "Outer.method.inner"
    assert dup.enclosing("m.py", line_of["return 2"], tmp_path) == "top"


def test_clone_site_is_keyed_by_function_names(tmp_path: Path) -> None:
    paths = _write(tmp_path, original=_ORIGINAL, copy=_RENAMED_COPY)
    (clone,) = dup.find_clones(dup.collect(paths, root=tmp_path), min_tokens=35)
    assert dup.site(clone, tmp_path) == ("copy.py::lookup", "original.py::find")


def test_site_survives_moving_lines(tmp_path: Path) -> None:
    """Adding lines above a copy changes its line numbers, not its site."""
    paths = _write(tmp_path, original=_ORIGINAL, copy=_RENAMED_COPY)
    (before,) = dup.find_clones(dup.collect(paths, root=tmp_path), min_tokens=35)
    site_before = dup.site(before, tmp_path)  # read against the file as it is now
    paths = _write(tmp_path, original="\n\n\n# padding\n" + _ORIGINAL, copy=_RENAMED_COPY)
    (after,) = dup.find_clones(dup.collect(paths, root=tmp_path), min_tokens=35)
    assert (before.a_start, before.b_start) != (after.a_start, after.b_start)
    assert dup.site(after, tmp_path) == site_before


def test_ratchet_new_clone_fails(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(dup, "BASELINE", {})
    paths = _write(tmp_path, original=_ORIGINAL, copy=_RENAMED_COPY)
    assert dup.main([str(p) for p in paths] + ["--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "NEW duplicate" in out and "copy.py::lookup" in out


def test_ratchet_stale_entry_fails(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(dup, "BASELINE", {("gone.py::a", "gone.py::b"): "#1"})
    paths = _write(tmp_path, cache=_UNRELATED)
    assert dup.main([str(p) for p in paths] + ["--root", str(tmp_path)]) == 1
    assert "no longer found" in capsys.readouterr().out


def test_ratchet_exact_match_passes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(dup, "BASELINE", {("copy.py::lookup", "original.py::find"): "#1"})
    paths = _write(tmp_path, original=_ORIGINAL, copy=_RENAMED_COPY)
    assert dup.main([str(p) for p in paths] + ["--root", str(tmp_path)]) == 0


def test_repo_matches_the_baseline_exactly() -> None:
    """The ratchet on the real tree, run by pytest so CI enforces it even when
    pre-commit's file filter skips the hook."""
    streams = dup.collect([_ROOT / t for t in dup.DEFAULT_TARGETS])
    found = {dup.site(c) for c in dup.find_clones(streams)}
    assert found == set(
        dup.BASELINE
    ), f"new: {sorted(found - set(dup.BASELINE))}; stale: {sorted(set(dup.BASELINE) - found)}"


def test_every_baseline_entry_names_its_issue() -> None:
    for key, issue in dup.BASELINE.items():
        assert re.fullmatch(r"#\d+", issue), (key, issue)
        assert key == tuple(sorted(key)), f"baseline key must be sorted: {key}"


def test_default_targets_exist() -> None:
    for target in dup.DEFAULT_TARGETS:
        assert (_ROOT / target).exists(), target


def test_precommit_hook_is_blocking() -> None:
    """The hook runs the ratchet (#636): no --report-only escape hatch."""
    config = yaml.safe_load((_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = {h["id"]: h for repo in config["repos"] for h in repo["hooks"]}
    hook = hooks["duplicate-code-report"]
    assert "scripts/duplicate_code_report.py" in hook["entry"]
    assert "--report-only" not in hook["entry"]
    assert "--report-only" not in hook.get("args", [])
    assert hook.get("verbose") is True  # the report stays visible when it passes
