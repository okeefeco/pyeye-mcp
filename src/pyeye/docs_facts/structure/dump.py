"""Collect a codebase's structure through pyeye: the dump (#1092).

Ported from the RFC #1083 trial's ``scripts/dump.py`` (2026-11-22), with three
changes:

* modules come from the files on disk (:func:`pyeye.project_layout.iter_module_files`,
  named by the one file -> module mapper), not from an ``outline`` survey of one
  top package, so a repository with several packages is covered;
* class members come from ``expand(members)`` too, not from the AST;
* ``imports`` (with ``type_only``, #1081), ``unresolved_imports`` and
  ``unreadable_definitions`` (#1074) are recorded.

One-line docstrings come from the AST, as in the trial: a docstring is written
in the source, so reading it is static, and it saves an ``inspect`` per symbol.

Static only (ruling C19). Jedi never loads the analysed repository's compiled
extensions (``_jedi_project.LOAD_UNSAFE_EXTENSIONS`` is off). :func:`source_only`
also refuses the compiled modules on pyeye's own interpreter path, ``builtins``
aside, so they read as unresolved instead.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import dataclasses
import fnmatch
from collections.abc import Generator, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The pyeye kinds the dump keeps as definitions; variables and attributes are
#: not definitions (the trial kept functions and classes only).
DEFINITION_KINDS = frozenset({"function", "class", "method"})

#: Longest one-line docstring kept, in characters (the trial's cut).
SUMMARY_CHARS = 110


@dataclass(frozen=True)
class Unreadable:
    """A definition pyeye couldn't read (#1074): reported, never dropped silently."""

    handle: str
    kind: str
    line: int
    reason: str


@dataclass(frozen=True)
class Definition:
    """A function, class or method, as ``expand(members)`` lists it.

    Attributes:
        handle: Its canonical handle.
        kind: ``function``, ``class`` or ``method``.
        module: The module it is defined in.
        owner: The module or class that lists it as a member.
        signature: pyeye's one-line signature, or ``None`` when pyeye gives none.
        summary: The first non-blank line of its docstring, ``""`` if it has none.
    """

    handle: str
    kind: str
    module: str
    owner: str
    signature: str | None
    summary: str


@dataclass(frozen=True)
class Module:
    """One module's facts.

    Attributes:
        handle: Its dotted name.
        file: Its file, relative to the root, with forward slashes.
        summary: The first line of its docstring, ``""`` if it has none.
        imported_by: How many modules import it (``total`` when pyeye capped the
            list, #435), or ``None`` if pyeye couldn't measure it.
        importers: The importing modules pyeye listed.
        imports: What it imports at runtime (pyeye's ``imports`` stubs that are
            not ``type_only``), project and external.
        type_only_imports: What it imports only under ``TYPE_CHECKING`` (#1081).
        unresolved_imports: Imports pyeye couldn't resolve, as written.
        measured_imports: Whether pyeye's ``imports`` edge answered at all.
    """

    handle: str
    file: str
    summary: str
    imported_by: int | None
    importers: tuple[str, ...]
    imports: tuple[str, ...]
    type_only_imports: tuple[str, ...]
    unresolved_imports: tuple[str, ...]
    measured_imports: bool


@dataclass(frozen=True)
class Dump:
    """A codebase's structure.

    Attributes:
        modules: Every module, sorted by handle.
        definitions: Every function, class and method, in member order.
        unreadable: Definitions pyeye listed as unreadable (#1074).
        unmapped: Files the file -> module mapper names no module for.
        unresolved: Modules pyeye couldn't resolve or read (not found, or
            ``unparseable``), with the reason.
        refused: Compiled modules :func:`source_only` refused to load.
    """

    modules: tuple[Module, ...]
    definitions: tuple[Definition, ...]
    unreadable: tuple[Unreadable, ...] = ()
    unmapped: tuple[str, ...] = ()
    unresolved: tuple[tuple[str, str], ...] = ()
    refused: tuple[str, ...] = ()
    by_handle: dict[str, Definition] = field(
        default_factory=dict, init=False, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        """Index the definitions by handle."""
        self.by_handle.update((d.handle, d) for d in self.definitions)


def first_line(doc: str | None) -> str:
    """The first non-blank line of *doc*, stripped and cut to :data:`SUMMARY_CHARS`."""
    for line in (doc or "").strip().splitlines():
        if line.strip():
            return line.strip()[:SUMMARY_CHARS]
    return ""


def selected(rel: str, include: Sequence[str], exclude: Sequence[str]) -> bool:
    """Whether the repo-relative path *rel* is in scope.

    Patterns are :mod:`fnmatch` patterns on the forward-slash path, where ``*``
    also matches ``/``. A file is in scope when it matches some *include*
    pattern and no *exclude* pattern.
    """
    return any(fnmatch.fnmatchcase(rel, p) for p in include) and not any(
        fnmatch.fnmatchcase(rel, p) for p in exclude
    )


def docstrings(source: str) -> tuple[str, dict[str, str]]:
    """The module's summary, and each definition's summary by its dotted path in the file.

    A definition nested in a compound statement (``if``, ``try``, ``with``,
    ``for``, ``while``, ``match``) counts as the enclosing scope's, as pyeye's
    ``members`` lists it. The first docstring a name has wins (an ``@overload``
    stub has none; its implementation does).

    Raises:
        SyntaxError: If *source* doesn't parse.
    """
    tree = ast.parse(source)
    found: dict[str, str] = {}
    for path, node in walk_definitions(tree.body):
        if not found.get(path):
            found[path] = first_line(ast.get_docstring(node))
    return first_line(ast.get_docstring(tree)), found


Def = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def walk_definitions(body: Sequence[ast.stmt], prefix: str = "") -> Iterator[tuple[str, Def]]:
    """Yield ``(dotted path, node)`` for every definition in a scope, classes recursed.

    A function's body is a new scope and isn't entered: a nested function is
    not a member. A class's body is, so methods and nested classes are yielded
    as ``Class.method``.
    """
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            path = f"{prefix}{stmt.name}"
            yield path, stmt
            if isinstance(stmt, ast.ClassDef):
                yield from walk_definitions(stmt.body, f"{path}.")
            continue
        for block in _blocks(stmt):
            yield from walk_definitions(block, prefix)


def _blocks(stmt: ast.stmt) -> Iterator[list[ast.stmt]]:
    """The statement lists inside a compound statement that stay in its scope."""
    body = getattr(stmt, "body", None)
    if isinstance(body, list):
        yield body
    for handler in getattr(stmt, "handlers", ()):
        yield handler.body
    for case in getattr(stmt, "cases", ()):
        yield case.body
    for name in ("orelse", "finalbody"):
        block = getattr(stmt, name, None)
        if isinstance(block, list):
            yield block


@contextlib.contextmanager
def source_only() -> Generator[list[str]]:
    """Hold Jedi to source: refuse every compiled module but ``builtins``.

    Yields the list the refused module names are appended to. A refused import
    reads as unresolved, as an uninstalled one does.

    Raises:
        RuntimeError: If Jedi no longer has the seam this patches. Refusing is
            the honest answer: running on would load compiled modules.
    """
    from jedi.inference import imports

    original = getattr(imports, "_load_builtin_module", None)
    if original is None:
        raise RuntimeError(
            "source_only: jedi.inference.imports._load_builtin_module is gone, so "
            "compiled modules can't be refused; not collecting"
        )
    refused: list[str] = []

    def refuse(inference_state: Any, import_names: Sequence[str], sys_path: Any) -> Any:
        name = ".".join(import_names)
        if name == "builtins":
            return original(inference_state, import_names, sys_path)
        refused.append(name)
        return None

    imports._load_builtin_module = refuse
    try:
        yield refused
    finally:
        imports._load_builtin_module = original


class Pyeye:
    """pyeye's operations on one project, called in process. Never raises on a lookup.

    Its project manager watches the project's files, so :meth:`close` it (or
    use it as a context manager) when done.
    """

    def __init__(self, root: Path) -> None:
        """Operations over the project at *root*; nothing starts until first use."""
        self.root = root
        self._manager: Any = None
        self._analyzer: Any = None

    def __enter__(self) -> Pyeye:
        """Use as a context manager: closed on exit."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close on leaving the ``with`` block."""
        self.close()

    def close(self) -> None:
        """Stop the project manager's watchers, if one was started."""
        if self._manager is not None:
            self._manager.cleanup_all()
            self._manager = None
            self._analyzer = None

    @property
    def analyzer(self) -> Any:
        """The project's analyzer, built on first use (configured packages honoured)."""
        if self._analyzer is None:
            from ...project_manager import ProjectManager

            self._manager = ProjectManager()
            self._analyzer = self._manager.get_analyzer(self.root.as_posix())
        return self._analyzer

    def expand(self, handle: str, edge: str) -> dict[str, Any]:
        """Walk *edge* from *handle* with pyeye's ``expand``, no stub cap."""
        from ...mcp.operations.expand import expand

        return asyncio.run(expand(handle, edge, self.analyzer, max_stubs=None))

    def inspect(self, handle: str) -> dict[str, Any]:
        """The ``inspect`` node pyeye gives for *handle*."""
        from ...mcp.operations.inspect import inspect

        return asyncio.run(inspect(handle, self.analyzer))

    def resolve(self, identifier: str) -> dict[str, Any]:
        """The ``resolve`` result pyeye gives for *identifier* (#1176): canonical handles."""
        from ...mcp.operations.resolve import resolve

        return dict(asyncio.run(resolve(identifier, self.analyzer)))

    def module_name(self, file: Path) -> str | None:
        """The file -> module mapper's name for *file*."""
        from ...project_layout import module_name_for_file

        return module_name_for_file(self.analyzer, file)


def relative(file: Path, root: Path) -> str:
    """*file*'s path relative to *root*, forward slashes; as given if it isn't inside."""
    from ...path_utils import relative_within

    inside = relative_within(file, root)
    return (inside if inside is not None else file).as_posix()


def module_files(root: Path, include: Sequence[str], exclude: Sequence[str]) -> list[Path]:
    """The in-scope module files under *root*, sorted."""
    from ...project_layout import iter_module_files

    return [f for f in iter_module_files(root) if selected(relative(f, root), include, exclude)]


def collect(
    root: Path,
    *,
    include: Sequence[str] = ("*",),
    exclude: Sequence[str] = (),
    strict_source: bool = False,
    pyeye: Pyeye | None = None,
) -> Dump:
    """Collect the dump for the in-scope modules under *root*.

    Args:
        root: The project root.
        include: :func:`selected` patterns for the files in scope.
        exclude: :func:`selected` patterns for files left out.
        strict_source: Hold Jedi to source (:func:`source_only`).
        pyeye: The operations to use, left open; by default one over *root*,
            closed on return.
    """
    files = module_files(root, include, exclude)
    guard: contextlib.AbstractContextManager[list[str]] = (
        source_only() if strict_source else contextlib.nullcontext([])
    )
    with contextlib.ExitStack() as stack:
        ops = pyeye or stack.enter_context(Pyeye(root))
        with guard as refused:
            dump = _collect(root, files, ops)
    return dataclasses.replace(dump, refused=tuple(sorted(set(refused))))


def _collect(root: Path, files: Sequence[Path], ops: Pyeye) -> Dump:
    modules: list[Module] = []
    definitions: list[Definition] = []
    unreadable: list[Unreadable] = []
    unmapped: list[str] = []
    unresolved: list[tuple[str, str]] = []
    for file in files:
        rel = relative(file, root)
        name = ops.module_name(file)
        if name is None:
            unmapped.append(rel)
            continue
        members = ops.expand(name, "members")
        if not members.get("found") or "stubs" not in members:
            unresolved.append((name, str(members.get("reason") or "not found")))
            continue
        try:
            summary, docs = docstrings(file.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            summary, docs = "", {}
        _members(name, name, "", members, docs, ops, definitions, unreadable)
        modules.append(_module(name, rel, summary, ops))
    return Dump(
        modules=tuple(sorted(modules, key=lambda m: m.handle)),
        definitions=tuple(definitions),
        unreadable=tuple(unreadable),
        unmapped=tuple(unmapped),
        unresolved=tuple(unresolved),
    )


def _members(
    module: str,
    owner: str,
    path: str,
    result: dict[str, Any],
    docs: dict[str, str],
    ops: Pyeye,
    out: list[Definition],
    unreadable: list[Unreadable],
) -> None:
    """Record *owner*'s member definitions, recursing into classes."""
    for item in result.get("unreadable_definitions") or ():
        unreadable.append(
            Unreadable(
                handle=f"{owner}.{item['name']}",
                kind=str(item.get("kind", "")),
                line=int(item.get("line", 0)),
                reason=str(item.get("reason", "")),
            )
        )
    for stub in result.get("stubs", ()):
        if stub.get("kind") not in DEFINITION_KINDS:
            continue
        handle = stub["handle"]
        leaf = handle.rsplit(".", 1)[-1]
        dotted = f"{path}{leaf}"
        out.append(
            Definition(
                handle=handle,
                kind=stub["kind"],
                module=module,
                owner=owner,
                signature=stub.get("signature"),
                summary=docs.get(dotted, ""),
            )
        )
        if stub["kind"] == "class":
            inner = ops.expand(handle, "members")
            if inner.get("found") and "stubs" in inner:
                _members(module, handle, f"{dotted}.", inner, docs, ops, out, unreadable)


def _module(name: str, rel: str, summary: str, ops: Pyeye) -> Module:
    by = ops.expand(name, "imported_by")
    importers: tuple[str, ...] = ()
    count: int | None = None
    if by.get("found") and "stubs" in by:
        importers = tuple(sorted(s["handle"] for s in by["stubs"]))
        count = int(by.get("total", len(importers)))
    imp = ops.expand(name, "imports")
    measured = bool(imp.get("found")) and "stubs" in imp
    stubs = imp.get("stubs", ()) if measured else ()
    return Module(
        handle=name,
        file=rel,
        summary=summary,
        imported_by=count,
        importers=importers,
        imports=tuple(sorted({s["handle"] for s in stubs if not s.get("type_only")})),
        type_only_imports=tuple(sorted({s["handle"] for s in stubs if s.get("type_only")})),
        unresolved_imports=tuple(sorted(set(imp.get("unresolved_imports") or ()))),
        measured_imports=measured,
    )
