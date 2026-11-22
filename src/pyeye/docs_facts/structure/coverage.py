"""The definitions on disk against the dump: a gap is reported, never silent (#1092).

Ported from the coverage check in the RFC #1083 trial's ``scripts/dump.py``
(2026-11-22), which caught #1074. The trial compared top-level names; this
compares every function, class and method, by handle, and reports both ways:

* **missing**: on disk, but neither in the dump nor listed as unreadable;
* **phantom**: in the dump, but not defined on disk (#1074's leaked locals);
* **unreadable**: on disk, and listed by pyeye as unreadable. Known, so not a gap,
  but reported so a reader knows the dump doesn't describe it;
* **skipped**: module files inside a dumped package that the dump has no module
  for. The dump's file list comes from pyeye's project scan, so a file that scan
  leaves out would otherwise pass unnoticed: a ``.py`` beside a dumped
  ``__init__.py``, or a sub-package (its ``__init__.py``) below one. Files the
  caller's own ``include``/``exclude`` leave out are not gaps.

Read with :mod:`ast` (static, ruling C19). A module file that doesn't parse
under this interpreter is listed in ``unparseable`` instead.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from .dump import Dump, relative, selected, walk_definitions

#: Module file names that make a directory a regular package.
INITS = ("__init__.py", "__init__.pyi")


@dataclass(frozen=True)
class Coverage:
    """The comparison, each list sorted.

    Attributes:
        on_disk: How many definitions the module files define.
        dumped: How many of them the dump holds.
        missing: Defined on disk; absent from the dump and not listed unreadable.
        phantom: In the dump; not defined on disk.
        unreadable: Defined on disk; listed by pyeye as unreadable.
        unparseable: Module files the AST can't read.
        skipped: Module files in a dumped package that have no module in the dump.
        unmapped: Module files no module name maps to (from the dump).
        unresolved: Modules pyeye couldn't resolve (from the dump).
    """

    on_disk: int
    dumped: int
    missing: tuple[str, ...]
    phantom: tuple[str, ...]
    unreadable: tuple[str, ...]
    unparseable: tuple[str, ...]
    unmapped: tuple[str, ...]
    unresolved: tuple[str, ...]
    skipped: tuple[str, ...] = ()

    @property
    def gaps(self) -> bool:
        """Whether anything is unaccounted for: a problem, never a pass."""
        return bool(
            self.missing
            or self.phantom
            or self.unparseable
            or self.unmapped
            or self.unresolved
            or self.skipped
        )


def defined(source: str, module: str) -> set[str]:
    """The handles of the functions, classes and methods *source* defines.

    Raises:
        SyntaxError: If *source* doesn't parse.
    """
    return {f"{module}.{path}" for path, _ in walk_definitions(ast.parse(source).body)}


def skipped(
    dump: Dump, root: Path, include: tuple[str, ...] = ("*",), exclude: tuple[str, ...] = ()
) -> list[str]:
    """Module files beside or just below a dumped package that the dump doesn't hold.

    Only regular packages are looked into (a namespace package has no file to
    anchor on), one level deep: a skipped sub-package is reported by its
    ``__init__``, and its own contents are looked into once it is dumped.
    """
    dumped = {m.file for m in dump.modules} | set(dump.unmapped)
    found: set[str] = set()
    for module in dump.modules:
        folder = (root / module.file).parent
        if Path(module.file).name not in INITS or not folder.is_dir():
            continue
        for entry in folder.iterdir():
            if entry.is_file() and entry.suffix == ".py":
                candidate = entry
            else:
                inits = [entry / name for name in INITS if (entry / name).is_file()]
                if not inits:
                    continue
                candidate = inits[0]
            rel = relative(candidate, root)
            if rel not in dumped and selected(rel, include, exclude):
                found.add(rel)
    return sorted(found)


def compare(
    dump: Dump, root: Path, include: tuple[str, ...] = ("*",), exclude: tuple[str, ...] = ()
) -> Coverage:
    """Compare the module files under *root* with *dump*.

    *include* and *exclude* are the ones the dump was collected with, so a file
    the caller left out isn't reported as skipped.
    """
    disk: set[str] = set()
    unparseable: list[str] = []
    for module in dump.modules:
        try:
            disk |= defined((root / module.file).read_text(encoding="utf-8"), module.handle)
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            unparseable.append(module.file)
    dumped = {d.handle for d in dump.definitions}
    unreadable = {u.handle for u in dump.unreadable}
    return Coverage(
        on_disk=len(disk),
        dumped=len(disk & dumped),
        missing=tuple(sorted(disk - dumped - unreadable)),
        phantom=tuple(sorted(dumped - disk)),
        unreadable=tuple(sorted(disk & unreadable)),
        unparseable=tuple(sorted(unparseable)),
        unmapped=tuple(sorted(dump.unmapped)),
        unresolved=tuple(sorted(f"{name} ({reason})" for name, reason in dump.unresolved)),
        skipped=tuple(skipped(dump, root, include, exclude)),
    )
