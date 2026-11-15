#!/usr/bin/env python3
"""Path normalisation and comparison have one owner (#717).

``pyeye.path_utils`` and ``pyeye.project_layout`` (the file <-> module mapper)
are the only modules that may normalise or compare filesystem paths. Elsewhere
in ``src/pyeye`` these AST patterns are flagged:

- ``resolve``: a zero-argument ``.resolve()`` call;
- ``os_path``: ``os.path.realpath`` / ``abspath`` / ``normpath`` / ``samefile``;
- ``relative_to``: ``.relative_to(...)`` / ``.is_relative_to(...)``, i.e. a
  containment check (use ``path_utils.relative_within``);
- ``str_compare``: ``str(<path-like>)`` used in a comparison, in
  ``.startswith`` / ``.endswith``, or as a dict key or subscript.

Path-like means a name or attribute called ``path``, ``file``, ``root`` or
``dir``, or ending in ``_path``, ``_file``, ``_root`` or ``_dir``. Log messages
and f-strings are not checked.

Three path bugs in one afternoon (#710, #714, #715) came from code that
normalised or compared paths its own way. Two copies of the same comparison
disagreed about symlinks, and the answer was an invented handle.

The check is a **ratchet**, with the same rules as the duplicate-code report
(#689). :data:`BASELINE` maps ``(file::qualname, rule)`` to the number of known
sites. A count above the baseline fails: route the new code through
``path_utils``. A count below the baseline, or a key that is gone, fails too:
lower or delete the entry. Keys use the enclosing function, so the check
survives line shifts.

Usage::

    check_cross_platform_paths.py                 # the ratchet over src/pyeye (blocking)
    check_cross_platform_paths.py --report        # list every site, exit 0
    check_cross_platform_paths.py --print-baseline  # the BASELINE literal for the current tree
    check_cross_platform_paths.py FILE...         # report only, for the given files
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src" / "pyeye"

#: The modules that own path normalisation and comparison.
OWNERS = frozenset({"src/pyeye/path_utils.py", "src/pyeye/project_layout.py"})

RULES = ("resolve", "os_path", "relative_to", "str_compare")

_OS_PATH_FUNCS = frozenset({"realpath", "abspath", "normpath", "samefile"})
_PATHLIKE = re.compile(r"^(?:path|file|root|dir)$|_(?:path|file|root|dir)$")

#: Known sites -> count. Only shrinks: each migration through path_utils lowers
#: or deletes an entry (#717). Generate with ``--print-baseline``.
BASELINE: dict[tuple[str, str], int] = {
    ("src/pyeye/async_utils.py::filtered_rglob", "relative_to"): 1,
    ("src/pyeye/config.py::ProjectConfig.__init__", "resolve"): 1,
    ("src/pyeye/config.py::ProjectConfig._normalise_config_path", "resolve"): 1,
    ("src/pyeye/config.py::ProjectConfig._read_pyright_extra_paths", "resolve"): 1,
    ("src/pyeye/mcp/operations/resolve.py::_resolve_file_only", "resolve"): 1,
    ("src/pyeye/mcp/operations/typeref.py::_cache_key", "resolve"): 1,
    ("src/pyeye/mcp/operations/typeref.py::_project_root", "resolve"): 1,
    ("src/pyeye/mcp/operations/typeref.py::invalidate_project", "resolve"): 1,
    ("src/pyeye/mcp/server.py::configure_packages", "resolve"): 1,
    ("src/pyeye/project_manager.py::ProjectManager._layout_roots", "resolve"): 1,
    ("src/pyeye/project_manager.py::ProjectManager._needs_update", "resolve"): 1,
    ("src/pyeye/project_manager.py::ProjectManager._on_files_changed", "resolve"): 1,
    ("src/pyeye/project_manager.py::ProjectManager._register", "resolve"): 1,
    ("src/pyeye/project_manager.py::ProjectManager._setup_watcher", "resolve"): 1,
    ("src/pyeye/project_manager.py::ProjectManager._watch", "resolve"): 1,
    ("src/pyeye/project_manager.py::ProjectManager.get_analyzer", "resolve"): 2,
    ("src/pyeye/project_manager.py::ProjectManager.invalidate_analyzer", "resolve"): 1,
    ("src/pyeye/project_manager.py::ProjectManager.register_project", "resolve"): 1,
    ("src/pyeye/resolver.py::_top_level_shadow", "resolve"): 1,
    ("src/pyeye/validation.py::PathValidator.validate_path", "relative_to"): 1,
    ("src/pyeye/validation.py::PathValidator.validate_path", "resolve"): 3,
}


@dataclass(frozen=True)
class Finding:
    """One flagged site."""

    file: str
    qualname: str
    rule: str
    line: int
    text: str

    @property
    def key(self) -> tuple[str, str]:
        """The ``(file::qualname, rule)`` baseline key for this finding."""
        return (f"{self.file}::{self.qualname}", self.rule)


def _is_pathlike(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return bool(_PATHLIKE.search(node.id))
    if isinstance(node, ast.Attribute):
        return bool(_PATHLIKE.search(node.attr))
    return False


def _str_of_pathlike(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "str"
        and len(node.args) == 1
        and _is_pathlike(node.args[0])
    )


class _Visitor(ast.NodeVisitor):
    def __init__(self, file: str, lines: list[str]) -> None:
        self.file = file
        self.lines = lines
        self.scope: list[str] = []
        self.findings: list[Finding] = []

    def _add(self, node: ast.AST, rule: str) -> None:
        line = getattr(node, "lineno", 0)
        text = self.lines[line - 1].strip() if 0 < line <= len(self.lines) else ""
        qualname = ".".join(self.scope) or "<module>"
        self.findings.append(Finding(self.file, qualname, rule, line, text))

    def _scoped(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = _scoped
    visit_AsyncFunctionDef = _scoped
    visit_ClassDef = _scoped

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr == "resolve" and not node.args and not node.keywords:
                self._add(node, "resolve")
            elif func.attr in ("relative_to", "is_relative_to") and node.args:
                self._add(node, "relative_to")
            elif (
                func.attr in _OS_PATH_FUNCS
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "path"
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "os"
            ):
                self._add(node, "os_path")
            elif func.attr in ("startswith", "endswith") and (
                _str_of_pathlike(func.value) or any(_str_of_pathlike(a) for a in node.args)
            ):
                self._add(node, "str_compare")
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        if any(_str_of_pathlike(n) for n in [node.left, *node.comparators]):
            self._add(node, "str_compare")
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if _str_of_pathlike(node.slice):
            self._add(node, "str_compare")
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        if any(k is not None and _str_of_pathlike(k) for k in node.keys):
            self._add(node, "str_compare")
        self.generic_visit(node)


def check_source(source: str, file: str) -> list[Finding]:
    """Every finding in *source* (the text of *file*, a repo-relative POSIX path)."""
    visitor = _Visitor(file, source.splitlines())
    visitor.visit(ast.parse(source, filename=file))
    return visitor.findings


def iter_files(root: Path = SRC) -> Iterator[Path]:
    """Every ``.py`` file under *root*, sorted, except the path owners."""
    for path in sorted(root.rglob("*.py")):
        if path.relative_to(REPO_ROOT).as_posix() not in OWNERS:
            yield path


def scan(paths: list[Path] | None = None) -> list[Finding]:
    """Findings in *paths* (default: every non-owner file under ``src/``)."""
    findings: list[Finding] = []
    for path in paths if paths is not None else list(iter_files()):
        rel = path.resolve().relative_to(REPO_ROOT).as_posix()
        if rel in OWNERS:
            continue
        findings += check_source(path.read_text(encoding="utf-8"), rel)
    return findings


def counts(findings: list[Finding]) -> dict[tuple[str, str], int]:
    """Number of findings per baseline key."""
    return dict(Counter(f.key for f in findings))


def ratchet(
    found: dict[tuple[str, str], int], baseline: dict[tuple[str, str], int]
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """``(grown, shrunk)`` keys: above the baseline, and below it (or gone)."""
    grown = sorted(k for k, n in found.items() if n > baseline.get(k, 0))
    shrunk = sorted(k for k, n in baseline.items() if found.get(k, 0) < n)
    return grown, shrunk


def _baseline_literal(found: dict[tuple[str, str], int]) -> str:
    lines = ["BASELINE: dict[tuple[str, str], int] = {"]
    for (site, rule), n in sorted(found.items()):
        lines.append(f'    ("{site}", "{rule}"): {n},')
    lines.append("}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the checker; return the process exit code."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--report", action="store_true", help="list every site and exit 0")
    parser.add_argument("--print-baseline", action="store_true", help="print the BASELINE literal")
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args(argv)

    findings = scan(args.paths or None)
    if args.print_baseline:
        print(_baseline_literal(counts(findings)))
        return 0
    if args.report or args.paths:
        for f in findings:
            print(f"{f.file}:{f.line}: [{f.rule}] {f.qualname}: {f.text}")
        print(f"path ownership (#717): {len(findings)} site(s) outside path_utils/project_layout")
        return 0

    grown, shrunk = ratchet(counts(findings), BASELINE)
    found = counts(findings)
    for key in grown:
        print(
            f"  NEW path normalisation/comparison at {key[0]} [{key[1]}]: "
            f"{found.get(key, 0)} > baseline {BASELINE.get(key, 0)}"
        )
        for f in findings:
            if f.key == key:
                print(f"      {f.file}:{f.line}: {f.text}")
    for key in shrunk:
        print(
            f"  fewer sites at {key[0]} [{key[1]}] than BASELINE says "
            f"({found.get(key, 0)} < {BASELINE[key]}): lower or delete the entry"
        )
    if grown:
        print(
            "  Route new path handling through pyeye.path_utils "
            "(relative_within, paths_equal, normalize_path) instead of adding to BASELINE."
        )
    print(
        f"path ownership (#717): {sum(found.values())} known site(s), "
        f"{len(grown)} new, {len(shrunk)} stale"
    )
    return 1 if grown or shrunk else 0


if __name__ == "__main__":
    sys.exit(main())
