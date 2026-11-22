"""Read pyeye's facts from its source, never by importing it (#1098, ruling C19).

docs-facts derives every fact from what is written in code. This module folds
module-level constants from ``ast`` with a deliberately small evaluator:

- literals (what :func:`ast.literal_eval` accepts, adjacent strings joined);
- a name bound to a constant in the same module, or imported from another
  ``pyeye`` module (``from pyeye.kinds import KINDS``, relative or absolute),
  folded there;
- f-strings over those;
- ``frozenset``, ``set``, ``tuple`` and ``list`` of a literal or of nothing;
- the ``-``, ``|``, ``&`` and ``+`` operators on sets, tuples and strings.

It never calls anything. Any other expression, such as a call, a
comprehension or an attribute of a module outside pyeye, is an
:class:`~.facts.ExtractionError` naming the file and line, so a constant that
stops being statically readable fails loudly instead of being guessed.

Modules are read from ``<root>/src/pyeye`` (the checkout the facts describe),
never through ``pyeye.__file__``.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path
from typing import Any

from .._module_scope import iter_module_scope_imports
from ..path_utils import relative_within
from .facts import ExtractionError

_PACKAGE = "pyeye"
#: Callables the folder evaluates: each takes zero or one folded argument.
_CONSTRUCTORS = {"frozenset": frozenset, "set": set, "tuple": tuple, "list": list}


def module_file(root: Path, module: str) -> Path:
    """The source file of *module* (``pyeye.x.y``) under *root*'s ``src/``."""
    parts = module.split(".")
    base = root / "src" / Path(*parts)
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    raise ExtractionError(f"{module}: no module file under {(root / 'src').as_posix()}")


@lru_cache(maxsize=64)
def _parse(path: Path, mtime_ns: int) -> ast.Module:  # noqa: ARG001 - the cache key
    return ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())


def parse(root: Path, module: str) -> ast.Module:
    """*module*'s syntax tree, cached by file and modification time."""
    path = module_file(root, module)
    return _parse(path, path.stat().st_mtime_ns)


def _assigned(body: list[ast.stmt], name: str) -> ast.expr | None:
    """The value of the last top-level ``name = ...`` / ``name: T = ...`` in *body*."""
    found = None
    for node in body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                found = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if isinstance(node.target, ast.Name) and node.target.id == name:
                found = node.value
    return found


def _imported_from(tree: ast.Module, module: str, name: str) -> tuple[str, str] | None:
    """``(module, name)`` when *name* is imported from a pyeye module, else ``None``."""
    package = module.rsplit(".", 1)[0] if not module.endswith(".__init__") else module
    # The one module-scope import walk (#360); a guarded import binds nothing reliably.
    for node in iter_module_scope_imports(tree, include_guarded=False):
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if (alias.asname or alias.name) != name:
                continue
            if node.level:
                anchor = package.split(".")[: len(package.split(".")) - node.level + 1]
                source = ".".join([*anchor, *(node.module.split(".") if node.module else [])])
            else:
                source = node.module or ""
            if source == _PACKAGE or source.startswith(_PACKAGE + "."):
                return source, alias.name
    return None


def _scope(root: Path, module: str, dotted: str) -> tuple[list[ast.stmt], str]:
    """The statement list *dotted* (``C.X`` or ``X``) is assigned in, and its last part."""
    tree = parse(root, module)
    body: list[ast.stmt] = tree.body
    *classes, name = dotted.split(".")
    for cls in classes:
        found = next((n for n in body if isinstance(n, ast.ClassDef) and n.name == cls), None)
        if found is None:
            raise ExtractionError(f"{module}: no class {cls!r}")
        body = found.body
    return body, name


def constant(root: Path, module: str, dotted: str) -> Any:
    """Fold the constant *dotted* (``X`` or ``Class.X``) of *module* under *root*."""
    body, name = _scope(root, module, dotted)
    value = _assigned(body, name)
    if value is None:
        if "." not in dotted:
            imported = _imported_from(parse(root, module), module, name)
            if imported is not None:
                return constant(root, *imported)
        raise ExtractionError(f"{module}: no module-level {dotted!r}")
    return _Folder(root, module).fold(value)


class _Folder:
    """Evaluates one module's constant expressions without calling anything."""

    def __init__(self, root: Path, module: str) -> None:
        self.root = root
        self.module = module
        path = module_file(root, module)
        rel = relative_within(path, root)
        self.where = (rel if rel is not None else path).as_posix()

    def name(self, name: str) -> Any:
        """The constant *name* refers to: this module's, or a pyeye module's it imports."""
        return constant(self.root, self.module, name)

    def refuse(self, node: ast.AST) -> ExtractionError:
        line = getattr(node, "lineno", 0)
        return ExtractionError(
            f"{self.where}:{line}: {ast.unparse(node)!r} isn't a statically readable "
            "constant: docs-facts never runs code (C19). Write it as a literal."
        )

    def fold(self, node: ast.expr) -> Any:
        try:
            return ast.literal_eval(node)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            pass
        if isinstance(node, ast.Name):
            return self.name(node.id)
        if isinstance(node, ast.JoinedStr):
            return "".join(self._fstring_part(part) for part in node.values)
        if isinstance(node, ast.Call):
            return self._constructor(node)
        if isinstance(node, ast.BinOp):
            return self._binop(node)
        if isinstance(node, ast.Tuple | ast.List | ast.Set):
            items = [self.fold(e) for e in node.elts]
            kind = {ast.Tuple: tuple, ast.List: list, ast.Set: set}[type(node)]
            return kind(items)
        if isinstance(node, ast.Dict) and None not in node.keys:
            return {self.fold(k): self.fold(v) for k, v in zip(node.keys, node.values, strict=True)}  # type: ignore[arg-type]
        raise self.refuse(node)

    def _fstring_part(self, part: ast.expr) -> str:
        if isinstance(part, ast.Constant):
            return str(part.value)
        if (
            isinstance(part, ast.FormattedValue)
            and part.conversion == -1
            and part.format_spec is None
        ):
            return str(self.fold(part.value))
        raise self.refuse(part)

    def _constructor(self, node: ast.Call) -> Any:
        func = node.func
        if not (
            isinstance(func, ast.Name)
            and func.id in _CONSTRUCTORS
            and not node.keywords
            and len(node.args) <= 1
        ):
            raise self.refuse(node)
        build = _CONSTRUCTORS[func.id]
        return build(self.fold(node.args[0])) if node.args else build()

    def _binop(self, node: ast.BinOp) -> Any:
        left, right = self.fold(node.left), self.fold(node.right)
        try:
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.BitOr):
                return left | right
            if isinstance(node.op, ast.BitAnd):
                return left & right
            if isinstance(node.op, ast.Add):
                return left + right
        except TypeError:
            pass
        raise self.refuse(node)


def call_args(root: Path, module: str, dotted: str, count: int) -> list[tuple[Any, ...]]:
    """The first *count* folded arguments of each call in the tuple or list *dotted*.

    For a registry written as calls, such as ``(Step("name", "summary", fn), ...)``:
    the literal arguments are read; the rest (a function) is never touched.
    """
    body, name = _scope(root, module, dotted)
    value = _assigned(body, name)
    folder = _Folder(root, module)
    if not isinstance(value, ast.Tuple | ast.List):
        raise (
            folder.refuse(value)
            if value is not None
            else ExtractionError(f"{module}: no module-level {dotted!r}")
        )
    rows = []
    for item in value.elts:
        if not isinstance(item, ast.Call) or len(item.args) < count:
            raise folder.refuse(item)
        rows.append(tuple(folder.fold(arg) for arg in item.args[:count]))
    return rows


def dict_keys(root: Path, module: str, dotted: str) -> list[str]:
    """The literal keys, in order, of the dict *dotted*; its values are never read."""
    body, name = _scope(root, module, dotted)
    value = _assigned(body, name)
    folder = _Folder(root, module)
    if not isinstance(value, ast.Dict):
        raise (
            folder.refuse(value)
            if value is not None
            else ExtractionError(f"{module}: no module-level {dotted!r}")
        )
    return [folder.fold(k) for k in value.keys if k is not None]


def docstring(root: Path, module: str, dotted: str) -> str | None:
    """The cleaned docstring of the function, class or method *dotted* in *module*."""
    body: list[ast.stmt] = parse(root, module).body
    node: ast.AST | None = None
    for part in dotted.split("."):
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
            raise ExtractionError(f"{module}: no {dotted!r}")
        body = getattr(node, "body", [])
    return ast.get_docstring(node)  # type: ignore[arg-type]


class Module:
    """A pyeye module's constants, read statically: ``Module(root, "pyeye.config").CONFIG_KEYS``.

    Each attribute is :func:`constant`, folded on access; nothing is imported.
    """

    def __init__(self, root: Path, module: str) -> None:
        """Read *module* (``pyeye.x``) under *root*'s ``src/``."""
        self._root = root
        self._module = module

    def __getattr__(self, name: str) -> Any:
        """The folded constant *name*; dunder lookups (copy, pickle) are not constants."""
        if name.startswith("__"):
            raise AttributeError(name)
        return constant(self._root, self._module, name)

    @property
    def file(self) -> Path:
        """The module's source file under the root."""
        return module_file(self._root, self._module)


class _FileFolder(_Folder):
    """Folds constants in one file of any repository; names resolve in that file only."""

    def __init__(self, root: Path, file: str) -> None:  # noqa: D107 - see the class
        self.root = root
        self.module = file
        self.where = file
        self.tree = _parse_file(root, file)

    def name(self, name: str) -> Any:
        """The constant *name* is bound to in this file; an import is never followed."""
        value = _assigned(self.tree.body, name)
        if value is None:
            raise ExtractionError(f"{self.where}: no module-level {name!r}")
        return self.fold(value)


def _parse_file(root: Path, file: str) -> ast.Module:
    path = root / file
    if not path.is_file():
        raise ExtractionError(f"{file}: no such file under {root.as_posix()}")
    return _parse(path, path.stat().st_mtime_ns)


def file_constant(root: Path, file: str, name: str) -> Any:
    """Fold the module-level constant *name* in *file*, any repository's (#1091).

    The same folding as :func:`constant`, but a name resolves only within
    *file*: another repository's imports are never followed, nor its code run.
    """
    return _FileFolder(root, file).name(name)
