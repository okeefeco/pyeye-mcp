"""``CHECK no-import: A -> B`` lines, checked against pyeye's ``imports`` (#1092).

Ported from the layering half of the RFC #1083 trial's ``scripts/validate_v2.py``
(2026-11-22). The trial's AST fallback for ``TYPE_CHECKING`` is gone: pyeye marks
those imports ``type_only`` (#1081), and they are ignored, not violations.

A check holds when no module under ``A`` (``A`` itself or ``A.*``) imports
anything under ``B`` at runtime. A runtime import is a non-``type_only`` stub of
the ``imports`` edge, or an import pyeye couldn't resolve, as written: an
unresolved import of ``B`` still breaks the layering. A check whose ``A`` names
no module can't be verified and is reported as such, never as holding.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

#: One check line. ``A`` and ``B`` are dotted module prefixes.
CHECK = re.compile(r"CHECK no-import:\s*([\w.]+)\s*->\s*([\w.]+)")


class Imports(Protocol):
    """What a check reads of a module: a :class:`~.dump.Module`, or its imports fact."""

    @property
    def handle(self) -> str:
        """The module's dotted name."""

    @property
    def imports(self) -> tuple[str, ...]:
        """What it imports at runtime."""

    @property
    def type_only_imports(self) -> tuple[str, ...]:
        """What it imports only under ``TYPE_CHECKING``."""

    @property
    def unresolved_imports(self) -> tuple[str, ...]:
        """Imports pyeye couldn't resolve, as written."""

    @property
    def measured_imports(self) -> bool:
        """Whether pyeye's ``imports`` edge answered."""


@dataclass(frozen=True)
class Check:
    """One ``CHECK no-import`` line: no module under :attr:`a` imports :attr:`b`."""

    a: str
    b: str
    line: int


@dataclass(frozen=True)
class Result:
    """What one check found.

    Attributes:
        check: The check.
        violations: ``(module, imported)`` runtime imports that break it.
        ignored: ``(module, imported)`` imports that would break it but are
            ``type_only``, so they don't.
        unmeasured: Modules under ``A`` whose imports pyeye couldn't read.
        verifiable: Whether ``A`` names any module at all.
    """

    check: Check
    violations: tuple[tuple[str, str], ...]
    ignored: tuple[tuple[str, str], ...]
    unmeasured: tuple[str, ...]
    verifiable: bool

    @property
    def holds(self) -> bool:
        """Whether the check is verified to hold."""
        return self.verifiable and not self.violations and not self.unmeasured


def checks(text: str) -> list[Check]:
    """Every check line in *text*, with its 1-based line number."""
    return [
        Check(found.group(1), found.group(2), number)
        for number, line in enumerate(text.splitlines(), 1)
        for found in CHECK.finditer(line)
    ]


def under(name: str, prefix: str) -> bool:
    """Whether the dotted *name* is *prefix* or inside it."""
    return name == prefix or name.startswith(f"{prefix}.")


def run(check: Check, modules: Iterable[Imports]) -> Result:
    """Check one line against the dumped modules."""
    violations: set[tuple[str, str]] = set()
    ignored: set[tuple[str, str]] = set()
    unmeasured: list[str] = []
    verifiable = False
    for module in modules:
        if not under(module.handle, check.a):
            continue
        verifiable = True
        if not module.measured_imports:
            unmeasured.append(module.handle)
            continue
        for target in (*module.imports, *module.unresolved_imports):
            if under(target, check.b):
                violations.add((module.handle, target))
        for target in module.type_only_imports:
            if under(target, check.b):
                ignored.add((module.handle, target))
    return Result(
        check=check,
        violations=tuple(sorted(violations)),
        ignored=tuple(sorted(ignored)),
        unmeasured=tuple(sorted(unmeasured)),
        verifiable=verifiable,
    )


def message(result: Result) -> str | None:
    """A finding's message for a check that doesn't hold, else ``None``."""
    head = f"CHECK no-import: {result.check.a} -> {result.check.b}"
    if not result.verifiable:
        return f"{head}: no module is under {result.check.a}, so it can't be verified"
    if result.violations:
        shown = ", ".join(f"{m} imports {t}" for m, t in result.violations[:3])
        more = len(result.violations) - 3
        return f"{head} is broken: {shown}" + (f" (and {more} more)" if more > 0 else "")
    if result.unmeasured:
        return f"{head}: pyeye couldn't read the imports of {', '.join(result.unmeasured[:3])}"
    return None
