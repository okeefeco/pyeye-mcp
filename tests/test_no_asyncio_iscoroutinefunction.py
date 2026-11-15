"""Fitness: nothing calls the deprecated ``asyncio.iscoroutinefunction`` (#763).

It is deprecated on Python 3.14.  Since #752 every plugin tool call goes through
``metrics_hook``, so one call site there flooded a 3.14 run with thousands of
``DeprecationWarning``s.  ``inspect.iscoroutinefunction`` is the replacement.
The warning only fires on 3.14, so this static scan guards every interpreter.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCANNED = ("src/pyeye", "tests")


def _calls(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "iscoroutinefunction"
        and isinstance(node.value, ast.Name)
        and node.value.id == "asyncio"
    ]


@pytest.mark.parametrize("root", SCANNED)
def test_no_asyncio_iscoroutinefunction(root: str) -> None:
    hits = [
        f"{path.relative_to(REPO_ROOT).as_posix()}:{line}"
        for path in sorted((REPO_ROOT / root).rglob("*.py"))
        for line in _calls(path)
    ]
    assert hits == [], f"use inspect.iscoroutinefunction (#763): {hits}"
