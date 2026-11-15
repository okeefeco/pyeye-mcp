"""Static standard-library facts for the resolver and the edges (#544, #329).

Jedi sees the standard library through typeshed, and for two kinds of name that
view misleads an agent. This module answers both **statically**: it reads
stdlib and typeshed sources with the AST, imports nothing, and evaluates
nothing, so the answer is the same on every machine.

**Private definition, public handle (#544).** CPython defines some public
classes in a private module and re-exports them: ``collections/abc.py`` is
``from _collections_abc import *``. Typeshed reverses that chain
(``collections.abc.Mapping`` → ``typing.Mapping``). pyeye follows the real
``.py`` chain to the definition (``class Mapping`` in ``_collections_abc.py``)
and names it by the PUBLIC re-exporting module, ``collections.abc.Mapping``: the
name user code imports and CPython documents. This is a narrow exception to
"re-exports collapse to the definition site". It applies only when the
definition is in a private (``_``-prefixed) stdlib module that exactly one
public stdlib module re-exports, by ``from _X import *`` or by an explicit
import of a name in its ``__all__``. A plain *usage* import is not a re-export
(``pathlib`` imports ``Sequence`` from ``_collections_abc`` to use it). Project
and third-party code keep the collapse rule.

**Platform decision point (#329).** ``os.path`` is ``posixpath`` or ``ntpath``
depending on the platform. Code is written against ``os.path``, so neither
implementation is the right place to point an agent. The location of an
``os.path`` name is the ``if sys.platform …`` block in typeshed's
``os/path.pyi`` that selects the implementation, the same on every OS. An
explicit table (:data:`PLATFORM_ALTERNATIVES`) says which names are
platform-selected; nothing is inferred heuristically.

This is a lower layer: it must not import ``pyeye.mcp``.
"""

from __future__ import annotations

import ast
import functools
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jedi

from pyeye._module_scope import iter_module_scope_imports

#: The stdlib source root of the interpreter pyeye runs on (the root
#: ``pyeye.scope`` classifies as stdlib).
_STDLIB_ROOT = Path(sysconfig.get_paths()["stdlib"])

#: Jedi's bundled typeshed stdlib stubs.
_TYPESHED_STDLIB = Path(jedi.__file__).parent / "third_party" / "typeshed" / "stdlib"

#: Platform-selected modules: the public name and the implementations a
#: ``sys.platform`` branch chooses between.
PLATFORM_ALTERNATIVES: dict[str, frozenset[str]] = {
    "os.path": frozenset({"posixpath", "ntpath"}),
}

#: Bound on ``from _X import …`` hops followed to a private definition.
_MAX_HOPS = 4

_DEFINITIONS = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass(frozen=True)
class StdlibDefinition:
    """A stdlib definition named by its public re-exporting module.

    Attributes:
        handle: The public handle (``collections.abc.Mapping``).
        name: The defined name (the leaf a ``class``/``def`` binds).
        file: The private module's source file.
        line: The ``class``/``def`` line.
    """

    handle: str
    name: str
    file: Path
    line: int


@dataclass(frozen=True)
class DecisionPoint:
    """The span of the ``sys.platform`` branch that selects an implementation."""

    file: Path
    line_start: int
    line_end: int
    column: int


def is_stdlib(dotted: str) -> bool:
    """Whether *dotted*'s top-level package is part of the standard library."""
    top = dotted.split(".", 1)[0]
    return bool(top) and top in sys.stdlib_module_names


# ---------------------------------------------------------------------------
# #544: private definition, public handle
# ---------------------------------------------------------------------------


def stdlib_definition(path: str) -> StdlibDefinition | None:
    """The definition of *path* when it is in a private stdlib module, or ``None``.

    Follows the real source chain from the module *path* names (``from _X
    import *`` / ``from _X import name`` into private stdlib modules) to a
    top-level ``class``/``def``, then down any remaining components through
    nested definitions. Returns ``None`` outside the #544 exception: not stdlib,
    not found, defined in a public module, or without exactly one public
    re-exporter.
    """
    if not is_stdlib(path):
        return None
    parts = path.split(".")
    for split_at in range(len(parts) - 1, 0, -1):
        module = ".".join(parts[:split_at])
        source = module if stdlib_module_file(module) is not None else _module_alias(module)
        if source is None:
            continue
        found = _find_definition(source, parts[split_at], hops=0)
        if found is None:
            return None
        def_module, node, file = found
        if not _is_private(def_module):
            return None
        public = public_reexporter(def_module, node.name)
        if public is None:
            return None
        target = _nested(node, parts[split_at + 1 :])
        if target is None:
            return None
        return StdlibDefinition(
            handle=".".join([public, node.name, *parts[split_at + 1 :]]),
            name=target.name,
            file=file,
            line=target.lineno,
        )
    return None


def public_handle(full_name: str) -> str | None:
    """The public handle for a name under a private stdlib module, or ``None``.

    ``_collections_abc.Mapping.get`` → ``collections.abc.Mapping.get``. Only the
    module part is renamed. ``None`` when *full_name* is not under a private
    stdlib module or that name has no single public re-exporter.

    Callers must pass only names whose definition is a stdlib file
    (:func:`pyeye.scope.is_stdlib_source`): a project package may share a
    stdlib name.
    """
    if not is_stdlib(full_name):
        return None
    parts = full_name.split(".")
    for split_at in range(len(parts) - 1, 0, -1):
        module = ".".join(parts[:split_at])
        if not _is_private(module) or stdlib_module_file(module) is None:
            continue
        public = public_reexporter(module, parts[split_at])
        return ".".join([public, *parts[split_at:]]) if public else None
    return None


@functools.cache
def public_reexporter(private_module: str, name: str) -> str | None:
    """The one public stdlib module that re-exports *name* from *private_module*.

    A re-export is ``from private_module import *`` (with *name* exported by
    the star) or ``from private_module import name`` where the public module
    lists *name* in a literal ``__all__``. Returns ``None`` for zero or several.
    A package that binds ``sub = _X`` after ``import _X`` re-exports the whole
    module as ``pkg.sub``. Only files containing ``from _X import`` or
    ``import _X`` are parsed.
    """
    needles = (f"from {private_module} import".encode(), f"import {private_module}".encode())
    found: set[str] = set()
    for file, module in _public_stdlib_files():
        try:
            data = file.read_bytes()
        except OSError:
            continue
        if not any(needle in data for needle in needles):
            continue
        tree = _parse(file)
        if tree is None:
            continue
        if _star_exports(private_module, name):
            # ``import _X`` + ``sub = _X`` in a package: ``pkg.sub`` IS ``_X``
            # (3.13+ ``collections/__init__.py``: ``abc = _collections_abc``).
            package = module if file.name == "__init__.py" else None
            for sub, target in _private_module_aliases(tree).items():
                if package is not None and target == private_module:
                    found.add(f"{package}.{sub}")
        exported = _dunder_all(tree)
        for node in _unguarded_from_imports(tree):
            if node.module != private_module:
                continue
            for alias in node.names:
                if (
                    alias.name == "*"
                    and _star_exports(private_module, name)
                    or alias.name == name
                    and alias.asname in (None, name)
                    and name in exported
                ):
                    found.add(module)
    return next(iter(found)) if len(found) == 1 else None


@functools.cache
def stdlib_module_file(module: str) -> Path | None:
    """The stdlib ``.py`` source of *module* (package ``__init__.py`` or module)."""
    if not is_stdlib(module):
        return None
    base = _STDLIB_ROOT.joinpath(*module.split("."))
    for candidate in (base / "__init__.py", base.with_suffix(".py")):
        if candidate.is_file():
            return candidate
    return None


def _module_alias(module: str) -> str | None:
    """The private module a public ``pkg.sub`` with no file of its own aliases.

    ``collections.abc`` has no ``.py`` since 3.13: ``collections/__init__.py``
    binds ``abc = _collections_abc``.
    """
    if "." not in module:
        return None
    package, sub = module.rsplit(".", 1)
    file = stdlib_module_file(package)
    tree = _parse(file) if file is not None else None
    if tree is None:
        return None
    return _private_module_aliases(tree).get(sub)


def _private_module_aliases(tree: ast.Module) -> dict[str, str]:
    """Top-level ``name = _X`` bindings of an unguarded ``import _X`` (a private stdlib module)."""
    imported: dict[str, str] = {}
    for node in iter_module_scope_imports(tree, include_guarded=False):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "." not in alias.name and is_stdlib(alias.name) and _is_private(alias.name):
                    imported[alias.asname or alias.name] = alias.name
    aliases: dict[str, str] = {}
    for stmt in tree.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value, ast.Name)
            and stmt.value.id in imported
        ):
            aliases[stmt.targets[0].id] = imported[stmt.value.id]
    return aliases


def _find_definition(
    module: str, name: str, *, hops: int
) -> tuple[str, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef, Path] | None:
    """Follow *module*'s ``from _X import`` chain to the ``class``/``def`` *name*."""
    file = stdlib_module_file(module)
    tree = _parse(file) if file is not None else None
    if file is None or tree is None:
        return None
    for node in tree.body:
        if isinstance(node, _DEFINITIONS) and node.name == name:
            return module, node, file
    if hops >= _MAX_HOPS:
        return None
    for node in _unguarded_from_imports(tree):
        if not (node.module and is_stdlib(node.module) and _is_private(node.module)):
            continue
        for alias in node.names:
            if alias.name == "*" and _star_exports(node.module, name):
                original = name
            elif (alias.asname or alias.name) == name:
                original = alias.name
            else:
                continue
            found = _find_definition(node.module, original, hops=hops + 1)
            if found is not None:
                return found
    return None


def _unguarded_from_imports(tree: ast.Module) -> list[ast.ImportFrom]:
    """Absolute ``from X import …`` statements that always run (#360's one walk).

    Unguarded only: following a re-export commits to WHICH object a name is
    bound to, and under a guard the binding may never run.
    """
    return [
        n
        for n in iter_module_scope_imports(tree, include_guarded=False)
        if isinstance(n, ast.ImportFrom) and n.level == 0
    ]


def _nested(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef, rest: list[str]
) -> ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef | None:
    for part in rest:
        body = node.body
        found = next((n for n in body if isinstance(n, _DEFINITIONS) and n.name == part), None)
        if found is None:
            return None
        node = found
    return node


def _star_exports(module: str, name: str) -> bool:
    """Whether ``from module import *`` binds *name* (``__all__``, else no ``_``)."""
    file = stdlib_module_file(module)
    tree = _parse(file) if file is not None else None
    if tree is None:
        return False
    exported = _dunder_all(tree)
    return name in exported if exported else not name.startswith("_")


def _dunder_all(tree: ast.Module) -> frozenset[str]:
    """The names of a literal top-level ``__all__``; empty when there is none."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            value = node.value
            if isinstance(value, ast.List | ast.Tuple):
                return frozenset(
                    e.value
                    for e in value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                )
    return frozenset()


def _is_private(module: str) -> bool:
    return any(part.startswith("_") and not part.endswith("__") for part in module.split("."))


@functools.lru_cache(maxsize=1)
def _public_stdlib_files() -> tuple[tuple[Path, str], ...]:
    """Public stdlib modules one level deep: ``x.py``, ``x/__init__.py``, ``x/y.py``."""
    out: list[tuple[Path, str]] = []
    for file in sorted(_STDLIB_ROOT.glob("*.py")) + sorted(_STDLIB_ROOT.glob("*/*.py")):
        rel = file.relative_to(_STDLIB_ROOT).with_suffix("").parts
        parts = [p for p in rel if p != "__init__"]
        module = ".".join(parts)
        if not parts or not is_stdlib(module) or _is_private(module) or "-" in module:
            continue
        out.append((file, module))
    return tuple(out)


@functools.cache
def _parse(file: Path) -> ast.Module | None:
    try:
        return ast.parse(file.read_bytes(), filename=file.as_posix())
    except (OSError, SyntaxError, ValueError):
        return None


# ---------------------------------------------------------------------------
# #329: platform decision point
# ---------------------------------------------------------------------------


@functools.cache
def platform_decision_point(handle: str) -> DecisionPoint | None:
    """The ``sys.platform`` branch that selects *handle*'s implementation.

    For a handle in :data:`PLATFORM_ALTERNATIVES` (``os.path`` or
    ``os.path.<name>``): the top-level ``if`` in the module's typeshed stub
    whose test reads ``sys.platform`` and whose branches import from the listed
    alternatives. ``None`` for anything else, or if the stub has no such block.
    """
    group = next(
        (g for g in PLATFORM_ALTERNATIVES if handle == g or handle.startswith(g + ".")), None
    )
    if group is None:
        return None
    alternatives = PLATFORM_ALTERNATIVES[group]
    base = _TYPESHED_STDLIB.joinpath(*group.split("."))
    stub = next((p for p in (base.with_suffix(".pyi"), base / "__init__.pyi") if p.is_file()), None)
    tree = _parse(stub) if stub is not None else None
    if stub is None or tree is None:
        return None
    for node in tree.body:
        if not isinstance(node, ast.If) or not _reads_sys_platform(node.test):
            continue
        end = node.end_lineno or node.lineno
        imported = {
            n.module
            for n in iter_module_scope_imports(tree)
            if isinstance(n, ast.ImportFrom)
            and node.lineno <= n.lineno <= end
            and n.module in alternatives
        }
        if imported == alternatives:
            return DecisionPoint(
                file=stub,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                column=node.col_offset,
            )
    return None


def _reads_sys_platform(expr: ast.expr) -> bool:
    """Whether *expr* reads ``sys.platform`` (structurally; ``ast.unparse`` imports)."""
    return any(
        isinstance(n, ast.Attribute)
        and n.attr == "platform"
        and isinstance(n.value, ast.Name)
        and n.value.id == "sys"
        for n in ast.walk(expr)
    )


class PlatformAnchor:
    """A Jedi ``Name`` located at its platform decision point (#329).

    ``module_path`` / ``line`` / ``column`` / ``end_line`` report the
    :class:`DecisionPoint`; everything else (``type``, ``name``,
    ``full_name``, signatures, ``goto``) is the wrapped ``Name``'s.
    """

    def __init__(self, name: Any, point: DecisionPoint) -> None:
        """Wrap *name*, reporting *point* as its location."""
        self._wrapped = name
        self.module_path = point.file
        self.line = point.line_start
        self.column = point.column
        self.end_line = point.line_end

    def __getattr__(self, attr: str) -> Any:
        """Delegate everything but the location to the wrapped ``Name``."""
        return getattr(self._wrapped, attr)

    def __repr__(self) -> str:
        """Show the wrapped ``Name`` and the decision point it reports."""
        return f"PlatformAnchor({self._wrapped!r} @ {self.module_path.name}:{self.line})"


def relocate_platform(handle: str, name: Any) -> Any:
    """*name* wrapped as a :class:`PlatformAnchor` if *handle* is platform-selected."""
    if name is None or isinstance(name, PlatformAnchor):
        return name
    point = platform_decision_point(handle)
    return PlatformAnchor(name, point) if point is not None else name
