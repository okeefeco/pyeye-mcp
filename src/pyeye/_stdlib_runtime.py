"""The running interpreter is the authority on standard-library facts (#544).

Jedi sees the standard library through typeshed, and typeshed sometimes
reverses the truth: it declares ``collections.abc.Mapping`` as a re-export of
``typing.Mapping``, while at runtime ``typing.Mapping`` is the alias and the class
lives in ``_collections_abc`` (named ``collections.abc.Mapping`` by CPython on
purpose). For a **standard-library** symbol, pyeye therefore asks the runtime:

- the canonical handle is the runtime's own ``__module__ + "." + __qualname__``,
  with a member following its owner class (``Mapping.get.__module__`` is
  ``_collections_abc``, but its owner is ``collections.abc.Mapping``);
- the location is the runtime definition's source.

This matches what Jedi already says elsewhere (``pathlib.Path`` on 3.13 is
``pathlib._local.Path``; ``json.JSONDecoder`` is ``json.decoder.JSONDecoder``).

**Safety boundary.** Only standard-library modules (``sys.stdlib_module_names``)
are ever imported, and never the few that act on import. Project and
site-packages code stays static: pyeye never imports it. pyeye's interpreter
may be a different Python version from the project's; for the stdlib that is an
accepted approximation.

This is a lower layer: it must not import ``pyeye.mcp``.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

logger = logging.getLogger(__name__)

#: Stdlib modules that act on import (open a browser, print, start a GUI). Never
#: imported for introspection.
_SIDE_EFFECT_MODULES: frozenset[str] = frozenset(
    {"antigravity", "this", "__hello__", "__phello__", "idlelib", "turtle", "turtledemo", "tkinter"}
)

#: Modules whose objects differ by host platform (``os.path`` is one of these).
#: Their handles are decided separately (#329), so this module does not name
#: them yet.
_PLATFORM_ALTERNATIVE_MODULES: frozenset[str] = frozenset({"posixpath", "ntpath"})


@dataclass(frozen=True)
class RuntimeDefinition:
    """Where the runtime says a stdlib symbol is defined.

    Attributes:
        handle: The runtime's own dotted name for the object.
        name: The object's ``__name__`` (the leaf a definition binds).
        file: The source file of the definition.
        line: The 1-based first line of the definition (a decorator, if any).
    """

    handle: str
    name: str
    file: Path
    line: int


def is_stdlib(dotted: str) -> bool:
    """Whether *dotted*'s top-level package is part of the standard library."""
    top = dotted.split(".", 1)[0]
    return bool(top) and top in sys.stdlib_module_names


def runtime_definition(dotted: str) -> RuntimeDefinition | None:
    """Return the runtime definition of the stdlib class or function *dotted*.

    Returns ``None`` when *dotted* is not stdlib, does not exist, is not a class
    or function (a module, a constant, an alias instance such as
    ``typing.Mapping``), has no Python source (a C implementation), or belongs to
    a platform-alternative module. Never raises.
    """
    if not is_stdlib(dotted) or dotted.split(".", 1)[0] in _SIDE_EFFECT_MODULES:
        return None
    try:
        obj = _lookup(dotted)
        if obj is None or not (inspect.isclass(obj) or inspect.isfunction(obj)):
            return None
        handle = _runtime_handle(obj)
        if handle is None:
            return None
        located = _locate(obj)
    except Exception as exc:  # introspection must never break resolution
        logger.debug("runtime_definition(%r) failed: %s", dotted, exc)
        return None
    if located is None:
        return None
    file, line = located
    return RuntimeDefinition(handle=handle, name=obj.__name__, file=file, line=line)


def _lookup(dotted: str) -> object | None:
    """Import the longest stdlib module prefix of *dotted* and walk the rest."""
    parts = dotted.split(".")
    for split_at in range(len(parts), 0, -1):
        module = _import_stdlib(".".join(parts[:split_at]))
        if module is None:
            continue
        obj: object = module
        for attr in parts[split_at:]:
            if not hasattr(obj, attr):
                return None
            obj = getattr(obj, attr)
        return obj
    return None


def _import_stdlib(module_dotted: str) -> ModuleType | None:
    try:
        return importlib.import_module(module_dotted)
    except Exception:
        return None


def _locate(obj: object) -> tuple[Path, int] | None:
    """The file and ``class``/``def`` line that define *obj*, or ``None``.

    ``inspect.getsourcefile`` follows ``__module__``, which is exactly what a
    renamed class gets wrong (``collections.abc.Mapping`` is not in
    ``collections/abc.py``). Code objects record the real file, so candidates
    come from them first, then from ``__module__``. The line is the definition's
    own line in that file's AST, found by ``__qualname__``.
    """
    qualname = obj.__qualname__  # type: ignore[attr-defined]
    for candidate in _candidate_files(obj):
        line = _definition_line(candidate, qualname)
        if line is not None:
            return candidate, line
    return None


def _candidate_files(obj: object) -> list[Path]:
    files: list[str] = []
    code = getattr(obj, "__code__", None)
    if code is not None:
        files.append(code.co_filename)
    if inspect.isclass(obj):
        for value in vars(obj).values():
            func = getattr(value, "__func__", getattr(value, "fget", value))
            func_code = getattr(func, "__code__", None)
            if func_code is not None:
                files.append(func_code.co_filename)
    module = sys.modules.get(getattr(obj, "__module__", "") or "")
    module_file = getattr(module, "__file__", None)
    if module_file:
        files.append(module_file)
    seen: dict[str, Path] = {}
    for f in map(_unfreeze, files):
        if f and f.endswith(".py") and f not in seen and Path(f).is_file():
            seen[f] = Path(f)
    return list(seen.values())


def _unfreeze(filename: str) -> str | None:
    """Map a frozen module's ``<frozen name>`` code filename to its source file.

    Since 3.11 some stdlib modules (``_collections_abc``, ``os``, ``posixpath``)
    are frozen into the interpreter; their code objects say ``<frozen name>``,
    while the module's ``__file__`` still names the ``.py`` source.
    """
    if not filename.startswith("<frozen ") or not filename.endswith(">"):
        return filename
    module = sys.modules.get(filename[len("<frozen ") : -1])
    module_file = getattr(module, "__file__", None)
    return module_file if isinstance(module_file, str) else None


def _definition_line(file: Path, qualname: str) -> int | None:
    """The line of the ``class``/``def`` at *qualname* in *file*'s AST."""
    from pyeye import file_artifact_cache

    try:
        body: list[ast.stmt] = file_artifact_cache.get_ast(file).body
    except Exception:
        return None
    node: ast.stmt | None = None
    for part in qualname.split("."):
        node = next(
            (
                n
                for n in body
                if isinstance(n, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
                and n.name == part
            ),
            None,
        )
        if node is None:
            return None
        body = node.body
    return node.lineno if node is not None else None


def _runtime_handle(obj: object) -> str | None:
    """``__module__.__qualname__``, with a member following its owner's module."""
    module = getattr(obj, "__module__", None)
    qualname = getattr(obj, "__qualname__", None)
    if not isinstance(module, str) or not isinstance(qualname, str) or "<" in qualname:
        return None
    head = qualname.split(".", 1)[0]
    owner = getattr(sys.modules.get(module), head, None)
    if owner is not None and owner is not obj and inspect.isclass(owner):
        owner_module = getattr(owner, "__module__", None)
        if isinstance(owner_module, str):
            module = owner_module
    if module in _PLATFORM_ALTERNATIVE_MODULES or not is_stdlib(module):
        return None
    return f"{module}.{qualname}"


def stdlib_canonical(full_name: str) -> str | None:
    """The runtime handle for a stdlib Jedi ``full_name``, or ``None`` if unchanged.

    The longest prefix of *full_name* that is a stdlib class or function is
    renamed to its runtime handle, and the rest is kept, so a member follows its
    owner (``_collections_abc.Mapping.__slots__`` →
    ``collections.abc.Mapping.__slots__``). Returns ``None`` when nothing
    changes: not stdlib, no runtime class/function along it, or already the
    runtime's own name.

    Callers must pass only names whose definition is in the standard library:
    the check here is by name, and a project package may share a stdlib name.
    """
    if not is_stdlib(full_name):
        return None
    parts = full_name.split(".")
    for split_at in range(len(parts), 1, -1):
        prefix = ".".join(parts[:split_at])
        found = runtime_definition(prefix)
        if found is None:
            continue
        canonical = ".".join([found.handle, *parts[split_at:]])
        return canonical if canonical != full_name else None
    return None
