"""Only path_utils / project_layout normalise or compare paths: the ratchet (#717)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_paths", _ROOT / "scripts" / "check_cross_platform_paths.py"
)
assert _spec and _spec.loader
checker = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = checker
_spec.loader.exec_module(checker)


def _rules(source: str) -> list[tuple[str, str]]:
    return [(f.qualname, f.rule) for f in checker.check_source(source, "src/pyeye/x.py")]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def f(p):\n    return p.resolve()\n", [("f", "resolve")]),
        ("import os\ndef f(p):\n    return os.path.realpath(p)\n", [("f", "os_path")]),
        ("import os\ndef f(p):\n    return os.path.abspath(p)\n", [("f", "os_path")]),
        ("def f(a, b):\n    return a.relative_to(b)\n", [("f", "relative_to")]),
        ("def f(a, b):\n    return a.is_relative_to(b)\n", [("f", "relative_to")]),
        ("def f(file_path, x):\n    return str(file_path) == x\n", [("f", "str_compare")]),
        ("def f(root, x):\n    return str(root).startswith(x)\n", [("f", "str_compare")]),
        ("def f(cache, file_path):\n    return cache[str(file_path)]\n", [("f", "str_compare")]),
        ("def f(src_dir):\n    return {str(src_dir): 1}\n", [("f", "str_compare")]),
        ("class C:\n    def m(self, p):\n        return p.resolve()\n", [("C.m", "resolve")]),
        ("x = Path('.').resolve()\n", [("<module>", "resolve")]),
    ],
)
def test_each_rule_flags_its_pattern(source: str, expected: list[tuple[str, str]]) -> None:
    assert _rules(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "def f(p):\n    return p.as_posix()\n",
        "def f(p):\n    logger.info(f'resolving {p}')\n",  # log messages / f-strings are fine
        "def f(name, x):\n    return str(name) == x\n",  # not path-like
        "def f(h):\n    return h.resolve('x')\n",  # resolve(arg) is some other API
        "def f(file_path):\n    return str(file_path)\n",  # str() alone is display
        "def f(a, b):\n    return a == b\n",
    ],
)
def test_narrow_rules_leave_these_alone(source: str) -> None:
    assert _rules(source) == []


def test_owner_modules_are_exempt() -> None:
    files = {p.relative_to(_ROOT).as_posix() for p in checker.iter_files()}
    assert "src/pyeye/path_utils.py" not in files
    assert "src/pyeye/project_layout.py" not in files
    assert "src/pyeye/resolver.py" in files


def test_ratchet_fails_both_ways() -> None:
    base = {("a.py::f", "resolve"): 2}
    assert checker.ratchet({("a.py::f", "resolve"): 2}, base) == ([], [])
    assert checker.ratchet({("a.py::f", "resolve"): 3}, base) == ([("a.py::f", "resolve")], [])
    assert checker.ratchet({("a.py::f", "resolve"): 1}, base) == ([], [("a.py::f", "resolve")])
    assert checker.ratchet({}, base) == ([], [("a.py::f", "resolve")])
    assert checker.ratchet({("b.py::g", "os_path"): 1}, {}) == ([("b.py::g", "os_path")], [])


def test_repo_matches_the_baseline_exactly() -> None:
    """The real tree: no new site, and no baselined site that has gone."""
    found = checker.counts(checker.scan())
    grown, shrunk = checker.ratchet(found, checker.BASELINE)
    assert not grown, f"new path normalisation outside path_utils: {grown}"
    assert not shrunk, f"baseline entries to lower or delete: {shrunk}"


def test_baseline_keys_name_real_rules() -> None:
    for (site, rule), n in checker.BASELINE.items():
        assert rule in checker.RULES and "::" in site and n > 0, (site, rule, n)


def test_cli_ratchet_exits_zero_on_the_repo(capsys: pytest.CaptureFixture[str]) -> None:
    assert checker.main([]) == 0
    assert "0 new, 0 stale" in capsys.readouterr().out
