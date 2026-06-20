#!/usr/bin/env python3
"""Measure AST-vs-``goto`` fallback in subclass base resolution (#419).

``find_subclasses`` resolves each class base AST-first (:func:`resolve_base` —
deterministic) and only falls back to Jedi forward ``goto`` (non-deterministic
across processes, #419) when the AST cannot commit. This script replicates the
cold-build resolution-table construction and classifies every class base in a
target project as an **AST hit** or a **``goto`` fallback**, so the fallback rate
can be measured and regressions caught.

It is the reproducible record behind #419's "reduce the fallback rate" criterion:
the ``import *`` re-export following that landed in #405 cut Django's fallback
from ~1636 punts to ~647 (≈93% AST hit), and the residual is dominated by
builtins/stdlib that ``goto`` resolves deterministically anyway.

Usage::

    uv run python scripts/measure_subclass_fallback.py /path/to/project

The script depends only on the public ``base_resolution`` helpers and the
``resolve_relative_import`` seam, so it never imports Jedi and runs in seconds.
"""

from __future__ import annotations

import ast
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

# Add src to path so the script runs without an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pyeye.analyzers.base_resolution import (  # noqa: E402
    build_import_table,
    build_module_defines,
    build_star_sources,
    resolve_base,
)
from pyeye.import_analyzer import resolve_relative_import  # noqa: E402


def _module_name(py_file: Path, root: Path) -> str:
    rel = py_file.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else py_file.stem


def _base_dotted(node: ast.expr) -> str | None:
    """Dotted name of a class-base expression (``Name``/``Attribute``), or None."""
    parts: list[str] = []
    cur: ast.expr = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


class Stats(NamedTuple):
    """AST-hit / goto-fallback tallies for one project's class bases."""

    modules: int
    total_bases: int
    ast_hits: int
    goto_fallbacks: int
    top_fallback_heads: list[tuple[str, int]]


def measure(root: Path) -> Stats:
    """Return AST-hit / goto-fallback counts for every class base under *root*."""
    py_files = sorted(root.rglob("*.py"), key=lambda p: p.as_posix())

    import_tables: dict[str, dict[str, str]] = {}
    module_defines: dict[str, dict[str, str]] = {}
    star_sources: dict[str, list[str]] = {}
    trees: dict[str, ast.Module] = {}

    for py_file in py_files:
        module = _module_name(py_file, root)
        if module in trees:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        trees[module] = tree
        is_package = py_file.name == "__init__.py"
        import_tables[module] = build_import_table(
            tree, module, resolve_relative_import, is_package
        )
        module_defines[module] = build_module_defines(tree)
        stars = build_star_sources(tree, module, resolve_relative_import, is_package)
        if stars:
            star_sources[module] = stars

    hits = 0
    punts = 0
    punt_heads: Counter[str] = Counter()
    for module, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for base in node.bases:
                dotted = _base_dotted(base)
                if not dotted or dotted == "object":
                    continue
                resolved = resolve_base(module, dotted, import_tables, module_defines, star_sources)
                if resolved is not None:
                    hits += 1
                else:
                    punts += 1
                    punt_heads[dotted.split(".")[0]] += 1

    return Stats(
        modules=len(trees),
        total_bases=hits + punts,
        ast_hits=hits,
        goto_fallbacks=punts,
        top_fallback_heads=punt_heads.most_common(20),
    )


def main(argv: list[str]) -> int:
    """Run the AST-hit vs goto-fallback measurement for a project root."""
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} <project-root>", file=sys.stderr)
        return 2
    root = Path(argv[1]).expanduser().resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    stats = measure(root)
    total = stats.total_bases or 1
    print(f"project root    : {root}")
    print(f"modules parsed  : {stats.modules}")
    print(f"class bases     : {stats.total_bases}")
    print(f"AST hits        : {stats.ast_hits}  ({100 * stats.ast_hits / total:.1f}%)")
    print(f"goto fallbacks  : {stats.goto_fallbacks}  ({100 * stats.goto_fallbacks / total:.1f}%)")
    print("top fallback heads (base's head identifier):")
    for name, count in stats.top_fallback_heads:
        print(f"  {count:5d}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
