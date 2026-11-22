"""Function signatures and their types, read from pyeye's source (#1098 PR B, ruling C19).

The MCP tool surface is a list of functions and their parameters. This module
reads them from ``ast`` without importing or running anything, beside
:mod:`.static` (module-level constants):

- :func:`signature`: a function's or method's parameters, in order, with literal
  defaults (``self`` and ``cls`` dropped);
- :func:`type_string`: an annotation rendered the way the MCP input schema
  renders it, following type aliases into the module that defines them;
- :func:`decorated`, :func:`tuple_names`, :func:`returned_literal`,
  :func:`returned_method_dict`, :func:`imported_from` and
  :func:`declared_params`: the registrations around them.

Anything it can't read without running code (a computed default, a type it
doesn't know, a return that isn't a literal) is an
:class:`~.facts.ExtractionError` naming the file and line. A fact that stops
being statically readable fails loudly; it is never guessed.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..path_utils import relative_within
from .facts import ExtractionError
from .static import module_file, parse

#: Annotations rendered as themselves (the JSON schema's scalar types).
_SCALARS = {"str": "str", "int": "int", "float": "float", "bool": "bool", "Path": "str"}
#: Annotations with no type the schema can state.
_ANY = {"Any", "object"}
_UNION_NAMES = {"Optional", "Union"}
#: A parameter MCP fills itself, so it never appears in the input schema.
_INJECTED = {"Context"}


@dataclass(frozen=True)
class Param:
    """One parameter as written: its annotation node and its literal default."""

    name: str
    annotation: ast.expr | None
    required: bool
    default: Any = None


def _where(root: Path, module: str, node: ast.AST) -> str:
    path = module_file(root, module)
    rel = relative_within(path, root)
    shown = rel.as_posix() if rel is not None else path.as_posix()
    return f"{shown}:{getattr(node, 'lineno', '?')}"


def _refuse(root: Path, module: str, node: ast.AST, what: str) -> ExtractionError:
    return ExtractionError(f"{_where(root, module, node)}: {what}")


def _find(root: Path, module: str, dotted: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    body: list[ast.stmt] = parse(root, module).body
    *owners, name = dotted.split(".")
    for owner in owners:
        cls = next((n for n in body if isinstance(n, ast.ClassDef) and n.name == owner), None)
        if cls is None:
            raise ExtractionError(f"{module}: no class {owner!r}")
        body = cls.body
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise ExtractionError(f"{module}: no function {dotted!r}")


def _literal(root: Path, module: str, node: ast.expr) -> Any:
    try:
        return ast.literal_eval(node)
    except ValueError:
        raise _refuse(root, module, node, f"{ast.unparse(node)} isn't a literal") from None


def signature(root: Path, module: str, dotted: str) -> list[Param]:
    """The parameters of *dotted* (``"func"`` or ``"Class.method"``) in *module*.

    Positional and keyword-only parameters, in order. ``self`` / ``cls`` of a
    method are dropped, and so is an injected MCP ``Context``; ``*args`` and
    ``**kwargs`` aren't parameters a schema can list, so they are refused.
    """
    node = _find(root, module, dotted)
    args = node.args
    if args.vararg or args.kwarg:
        raise _refuse(root, module, node, f"{dotted} takes *args/**kwargs")
    positional = [*args.posonlyargs, *args.args]
    # Defaults align to the END of the positional parameters, so pair them first.
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults))
    defaults += list(args.defaults)
    pairs = [
        *zip(positional, defaults, strict=True),
        *zip(args.kwonlyargs, args.kw_defaults, strict=True),
    ]
    if "." in dotted and positional and positional[0].arg in ("self", "cls"):
        pairs = pairs[1:]
    params = []
    for arg, default in pairs:
        annotation = arg.annotation
        if annotation is not None and ast.unparse(annotation) in _INJECTED:
            continue
        if default is None:
            params.append(Param(arg.arg, annotation, required=True))
        else:
            params.append(
                Param(arg.arg, annotation, required=False, default=_literal(root, module, default))
            )
    return params


def imported_from(root: Path, module: str, name: str) -> tuple[str, str] | None:
    """``(module, name)`` that *name* is imported from at *module*'s top level, if any."""
    package = module.split(".")
    for node in parse(root, module).body:
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if (alias.asname or alias.name) != name:
                continue
            if node.level:
                is_package = module_file(root, module).name == "__init__.py"
                base = package if is_package else package[:-1]
                base = base[: len(base) - node.level + 1]
                source = ".".join([*base, *([node.module] if node.module else [])])
            else:
                source = node.module or ""
            return source, alias.name
    return None


def _alias(root: Path, module: str, name: str, node: ast.expr) -> tuple[str, ast.expr] | None:
    """The type expression *name* is bound to, in *module* or the module it comes from."""
    for stmt in parse(root, module).body:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in stmt.targets
        ):
            return module, stmt.value
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            if stmt.target.id == name and stmt.value is not None:
                return module, stmt.value
    source = imported_from(root, module, name)
    if source and (source[0] == "pyeye" or source[0].startswith("pyeye.")):
        return _alias(root, source[0], source[1], node)
    return None


def _members(root: Path, module: str, node: ast.expr) -> list[str]:
    """The union members of *node*, flattened, each rendered."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _members(root, module, node.left) + _members(root, module, node.right)
    if isinstance(node, ast.Subscript) and ast.unparse(node.value) in _UNION_NAMES:
        inner = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        members = [m for part in inner for m in _members(root, module, part)]
        return members + (["None"] if ast.unparse(node.value) == "Optional" else [])
    if isinstance(node, ast.Name) and node.id not in _SCALARS and node.id not in _ANY:
        aliased = _alias(root, module, node.id, node)
        if aliased is not None and not isinstance(aliased[1], ast.Call):
            return _members(root, aliased[0], aliased[1])
    return [_single(root, module, node)]


#: Bare names the schema states without parameters.
_BARE = {**_SCALARS, **dict.fromkeys(_ANY, "any"), "list": "list[any]", "dict": "dict"}


def _generic(root: Path, module: str, node: ast.Subscript) -> str | None:
    """``list[X]``, ``dict[str, X]`` or a ``Literal`` of one scalar kind, else ``None``."""
    head = ast.unparse(node.value)
    args = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    if head in ("list", "List", "Sequence"):
        return f"list[{type_string(root, module, args[0])}]"
    if head in ("dict", "Dict", "Mapping"):
        value = type_string(root, module, args[-1])
        return "dict" if value == "any" else f"dict[str, {value}]"
    if head == "Literal":
        kinds = {type(a.value).__name__ for a in args if isinstance(a, ast.Constant)}
        if len(kinds) == 1 and kinds <= set(_SCALARS):
            return _SCALARS[kinds.pop()]
    return None


def _single(root: Path, module: str, node: ast.expr) -> str:
    """One non-union type, as the schema states it."""
    rendered: str | None = None
    if isinstance(node, ast.Constant) and node.value is None:
        rendered = "None"
    elif isinstance(node, ast.Name):
        rendered = _BARE.get(node.id)
    elif isinstance(node, ast.Subscript):
        rendered = _generic(root, module, node)
    if rendered is None:
        raise _refuse(root, module, node, f"can't render the type {ast.unparse(node)!r} statically")
    return rendered


def type_string(root: Path, module: str, annotation: ast.expr | None) -> str:
    """*annotation* as the MCP input schema states it (``str | list[str] | None``)."""
    if annotation is None:
        return "any"
    return " | ".join(_members(root, module, annotation))


def decorated(root: Path, module: str, decorator: str) -> list[str]:
    """Top-level functions in *module* carrying *decorator* (as written, e.g. ``mcp.tool()``)."""
    return [
        node.name
        for node in parse(root, module).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(ast.unparse(d) == decorator for d in node.decorator_list)
    ]


def _assigned(root: Path, module: str, name: str) -> ast.expr:
    for stmt in parse(root, module).body:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in stmt.targets
        ):
            return stmt.value
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            if stmt.target.id == name and stmt.value is not None:
                return stmt.value
    raise ExtractionError(f"{module}: no module-level {name!r}")


def tuple_names(root: Path, module: str, name: str) -> list[str]:
    """The names in the tuple *name* is bound to (``ADMIN_TOOLS = (a, b)``)."""
    value = _assigned(root, module, name)
    if not isinstance(value, ast.Tuple) or not all(isinstance(e, ast.Name) for e in value.elts):
        raise _refuse(root, module, value, f"{name} isn't a tuple of names")
    return [e.id for e in value.elts if isinstance(e, ast.Name)]


def declared_params(root: Path, module: str, name: str) -> list[tuple[str, ast.expr, Any]]:
    """``(name, annotation node, default)`` from a tuple of ``(name, annotation, default)``."""
    value = _assigned(root, module, name)
    rows = []
    for row in value.elts if isinstance(value, ast.Tuple) else []:
        if not (isinstance(row, ast.Tuple) and len(row.elts) == 3):  # noqa: PLR2004 - a triple
            raise _refuse(root, module, row, f"{name} rows are (name, annotation, default)")
        rows.append(
            (_literal(root, module, row.elts[0]), row.elts[1], _literal(root, module, row.elts[2]))
        )
    if not rows:
        raise _refuse(root, module, value, f"{name} isn't a tuple of (name, annotation, default)")
    return rows


def _returned(root: Path, module: str, dotted: str) -> ast.expr:
    node = _find(root, module, dotted)
    returns = [n for n in ast.walk(node) if isinstance(n, ast.Return) and n.value is not None]
    if len(returns) != 1:
        raise _refuse(root, module, node, f"{dotted} has {len(returns)} return values, not one")
    value = returns[0].value
    assert value is not None
    return value


def returned_literal(root: Path, module: str, dotted: str) -> Any:
    """The literal *dotted* returns (``def name(self): return "Django"``)."""
    return _literal(root, module, _returned(root, module, dotted))


def returned_method_dict(root: Path, module: str, dotted: str) -> list[tuple[str, str]]:
    """``(key, method)`` pairs of a returned ``{"key": self.method, ...}``, in order."""
    value = _returned(root, module, dotted)
    if not isinstance(value, ast.Dict):
        raise _refuse(root, module, value, f"{dotted} doesn't return a dict literal")
    pairs = []
    for key, item in zip(value.keys, value.values, strict=True):
        if not (
            isinstance(key, ast.Constant)
            and isinstance(key.value, str)
            and isinstance(item, ast.Attribute)
            and isinstance(item.value, ast.Name)
            and item.value.id == "self"
        ):
            raise _refuse(root, module, item, f'{dotted} entries are "name": self.method')
        pairs.append((key.value, item.attr))
    return pairs
