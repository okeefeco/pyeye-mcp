"""A small project for the structure-extractor tests (#1092), written into a tmp dir.

Each fact family has something to find:

* ``pkg.paths.helper`` / ``pkg.util.normalise_path``: a delegation (the second calls
  the first) with overlapping names and docstrings;
* ``pkg.old.old_helper``: an unconditional deprecation; ``pkg.old.maybe_old``: a
  conditional one;
* ``pkg.shapes``: an override (``Base.area`` / ``Square.area``) and siblings
  (``Square`` / ``Circle`` share ``Base``);
* ``pkg.cfg.load_config`` / ``pkg.settings.read_config``: a possible duplicate
  no rule explains;
* ``pkg.hooks``: ``process`` implemented by three classes, an interface hook;
* ``pkg.shapes`` imports ``pkg.util`` only under ``TYPE_CHECKING``; ``pkg.util``
  imports ``pkg.paths`` at runtime; ``pkg.cfg`` imports a missing module;
* ``pkg.star``: a PEP 646 ``*args`` def pyeye can't read (#1074);
* ``bad-dir/x.py``: a file no module name maps to.
"""

from __future__ import annotations

from pathlib import Path

FILES: dict[str, str] = {
    "pkg/__init__.py": '"""The package."""\n',
    "pkg/paths.py": (
        '"""Path helpers."""\n\n'
        "SEPARATOR = '/'  # a variable: not a definition\n\n\n"
        "def helper(path: str, strict: bool = False) -> str:\n"
        '    """Normalise a file path.\n\n    More detail.\n    """\n'
        "    return path\n"
    ),
    "pkg/util.py": (
        "from pkg.paths import helper\n\n\n"
        "def normalise_path(path: str) -> str:\n"
        '    """Normalise a file path, the util way."""\n'
        "    return helper(path)\n"
    ),
    "pkg/old.py": (
        "import warnings\n\n\n"
        "def old_helper(path):\n"
        '    """Old path helper."""\n'
        '    warnings.warn("use helper", DeprecationWarning)\n'
        "    return path\n\n\n"
        "def maybe_old(path, legacy=False):\n"
        '    """Maybe old path helper."""\n'
        "    if legacy:\n"
        '        warnings.warn("legacy", DeprecationWarning)\n'
        "    return path\n"
    ),
    "pkg/shapes.py": (
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n"
        "    from pkg import util\n\n\n"
        "class Base:\n"
        '    """A shape."""\n\n'
        "    def area(self) -> float:\n"
        "        return 0.0\n\n\n"
        "class Square(Base):\n"
        "    def area(self) -> float:\n"
        "        return 1.0\n\n"
        "    def scale_shape(self, factor: float) -> None:\n"
        "        pass\n\n\n"
        "class Circle(Base):\n"
        "    def resize_shape(self, factor: float) -> None:\n"
        "        pass\n"
    ),
    "pkg/cfg.py": (
        "import missing_dependency\n\n\n"
        "def load_config(config_file: str) -> dict:\n"
        '    """Load the configuration file."""\n'
        "    return {}\n"
    ),
    "pkg/settings.py": (
        "def read_config(config_file: str) -> dict:\n"
        '    """Read the configuration file."""\n'
        "    return {}\n"
    ),
    "pkg/hooks.py": (
        "class One:\n    def process(self): ...\n\n\n"
        "class Two:\n    def process(self): ...\n\n\n"
        "class Three:\n    def process(self): ...\n"
    ),
    "pkg/star.py": (
        "def star(*args: *tuple[int, ...]) -> None: ...\n\n\n" "def after_star() -> None: ...\n"
    ),
    "bad-dir/x.py": "def orphan(): ...\n",
}


def write_project(root: Path) -> Path:
    """Write :data:`FILES` under *root* and return it."""
    for rel, text in FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return root
