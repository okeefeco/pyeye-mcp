"""Entry-point facts: console scripts and ``python -m`` module entry points.

Console scripts come from ``[project.scripts]`` in ``pyproject.toml``; module
entry points are the packages under ``pyeye`` that have a ``__main__.py``.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterator
from pathlib import Path

from ...async_utils import filtered_rglob
from ...path_utils import relative_within
from ..facts import Bindable, Fact, code, table, view

PREFIXES = ("cli",)


def extract(root: Path) -> Iterator[Bindable]:
    """Yield a fact per console script and per module entry point.

    The package is the checkout's ``src/pyeye``, never the imported one (#1098, C19).
    """
    return _facts(root, root / "src" / "pyeye")


def _facts(root: Path, package: Path) -> Iterator[Bindable]:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    scripts = [
        Fact(f"cli.script.{name}", {"target": target}, code(name))
        for name, target in sorted(project.get("scripts", {}).items())
    ]
    modules = []
    for main in sorted(filtered_rglob("__main__.py", package)):
        rel = relative_within(main.parent, package)
        if rel is None:
            continue
        module = ".".join(("pyeye", *rel.parts))
        command = f"python -m {module}"
        modules.append(Fact(f"cli.module.{module}", {"command": command}, code(command)))
    yield from scripts
    yield from modules
    rows = [[s.markdown, "console script", code(s.value["target"])] for s in scripts]
    rows += [[m.markdown, "module", code(m.id[len("cli.module.") :])] for m in modules]
    yield view("cli.all", [*scripts, *modules], table(["Command", "Kind", "Runs"], rows))
