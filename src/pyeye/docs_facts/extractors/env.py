"""Environment-variable facts: every ``PYEYE_*`` variable pyeye reads.

Two sources, both read from the installed package's own source:

- ``settings.py``: each ``self.<attr> = self._get_<kind>_env("PYEYE_X", default,
  min_val=..., max_val=...)`` call gives the type, default and range.
  ``DEPRECATED_ENV_VARS`` marks the ones with no effect.
- every other module: a literal ``os.environ.get("PYEYE_X", default)``,
  ``os.getenv(...)`` or ``os.environ["PYEYE_X"]`` read.

The "loaded *and* used" rule (#556): a settings variable whose attribute
nothing outside ``settings.py`` reads has status ``unused``, not ``live``.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ... import settings as settings_module
from ...async_utils import filtered_rglob
from ...path_utils import relative_within
from ..facts import Bindable, ExtractionError, Fact, code, literal, table, view

PREFIXES = ("env",)

_KINDS = {"_get_int_env": "int", "_get_float_env": "float", "_get_bool_env": "bool"}


_ENV_NAME = re.compile(r"PYEYE_[A-Z0-9_]+")


def _literal(node: ast.expr, what: str) -> Any:
    """The literal value of *node*; anything else can't be documented truthfully."""
    try:
        return ast.literal_eval(node)
    except ValueError:
        raise ExtractionError(
            f"{what} is not a literal (line {node.lineno}); the env extractor can't " "document it"
        ) from None


def _settings_vars(tree: ast.Module) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Call)):
            continue
        call = node.value
        func = call.func
        if not (isinstance(func, ast.Attribute) and func.attr in _KINDS):
            continue
        if not (isinstance(node.target, ast.Attribute) and call.args):
            continue
        name = _literal(call.args[0], f"the variable name passed to {func.attr}")
        if not isinstance(name, str):
            raise ExtractionError(f"{func.attr} is called with a non-string name {name!r}")
        keywords = {k.arg: _literal(k.value, f"{name}'s {k.arg}") for k in call.keywords}
        found[name] = {
            "attribute": node.target.attr,
            "type": _KINDS[func.attr],
            "default": _literal(call.args[1], f"{name}'s default") if len(call.args) > 1 else None,
            "min": keywords.get("min_val"),
            "max": keywords.get("max_val"),
        }
    return found


def _is_environ(node: ast.expr) -> bool:
    """``os.environ`` or a bare ``environ`` (``from os import environ``)."""
    return (isinstance(node, ast.Attribute) and node.attr == "environ") or (
        isinstance(node, ast.Name) and node.id == "environ"
    )


def _read_args(node: ast.AST) -> list[ast.expr]:
    """The arguments of an environment read (name first), or ``[]``."""
    if isinstance(node, ast.Call):
        func = node.func
        # os.environ.get(...), environ.get(...), os.getenv(...): never <obj>.getenv,
        # which could be any object's method.
        is_os_getenv = (
            func.attr == "getenv" and isinstance(func.value, ast.Name) and func.value.id == "os"
            if isinstance(func, ast.Attribute)
            else False
        )
        if isinstance(func, ast.Attribute) and (
            (func.attr == "get" and _is_environ(func.value)) or is_os_getenv
        ):
            return list(node.args)
        if isinstance(func, ast.Name) and func.id == "getenv":
            return list(node.args)
    elif isinstance(node, ast.Subscript) and _is_environ(node.value):
        return [node.slice]
    return []


def _computed_prefix(node: ast.AST) -> str | None:
    """The ``"PYEYE_..."`` prefix of an f-string or ``+`` that builds a name, else ``None``."""
    first: ast.expr | None = None
    if isinstance(node, ast.JoinedStr) and node.values:
        first = node.values[0]
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        first = node.left
    if (
        isinstance(first, ast.Constant)
        and isinstance(first.value, str)
        and first.value.startswith("PYEYE_")
        and " " not in first.value
    ):
        return first.value
    return None


def _direct_reads(tree: ast.Module, module: str) -> dict[str, Any]:
    """``PYEYE_*`` name -> literal default, for each direct environment read.

    Raises:
        ExtractionError: If a ``"PYEYE_*"`` literal is used other than as the
            name in a read (e.g. through a constant or a wrapper), since that
            variable would be missing from the docs.
    """
    found: dict[str, Any] = {}
    consumed: set[int] = set()
    for node in ast.walk(tree):
        args = _read_args(node)
        if not args or not isinstance(args[0], ast.Constant):
            continue
        name = args[0].value
        if isinstance(name, str) and _ENV_NAME.fullmatch(name):
            consumed.add(id(args[0]))
            default = _literal(args[1], f"{name}'s default") if len(args) > 1 else None
            found.setdefault(name, default)
    for node in ast.walk(tree):
        prefix = _computed_prefix(node)
        if prefix is not None and isinstance(node, ast.expr):
            raise ExtractionError(
                f"pyeye/{module} line {node.lineno} builds a variable name from {prefix!r}; "
                "a computed PYEYE_* name can't be documented, so spell it out"
            )
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _ENV_NAME.fullmatch(node.value)
            and id(node) not in consumed
        ):
            raise ExtractionError(
                f"pyeye/{module} line {node.lineno} uses {node.value!r} other than as the "
                "name in an os.environ / getenv read; read it directly so it's documented"
            )
    return found


def _range(value: dict[str, Any]) -> str:
    if value["type"] == "bool":
        return "true/false"
    low, high = value.get("min"), value.get("max")
    if low is None and high is None:
        return ""
    return f"{literal(low)}-{literal(high)}"


def _parse_package(package: Path) -> dict[str, ast.Module]:
    """Every module of *package*, parsed, by package-relative POSIX path."""
    trees: dict[str, ast.Module] = {}
    for path in sorted(filtered_rglob("*.py", package)):
        rel = relative_within(path, package)
        if rel is not None:
            trees[rel.as_posix()] = ast.parse(path.read_text(encoding="utf-8"))
    return trees


def _status(name: str, attribute: str, used_attributes: set[str]) -> dict[str, str]:
    if name in settings_module.DEPRECATED_ENV_VARS:
        return {"status": "deprecated", "deprecated": settings_module.DEPRECATED_ENV_VARS[name]}
    return {"status": "live" if attribute in used_attributes else "unused"}


def _row(fact: Fact) -> list[str]:
    value = fact.value
    status = value["status"]
    if status == "deprecated":
        status = f"deprecated, no effect: {value['deprecated']}"
    return [fact.markdown, literal(value["default"]), _range(value), status]


def extract(root: Path) -> Iterator[Bindable]:  # noqa: ARG001 - reads the installed package
    """Yield a fact per ``PYEYE_*`` variable, plus the group views."""
    settings_path = Path(settings_module.__file__)
    trees = _parse_package(settings_path.parent)
    settings_rel = settings_path.name
    used_attributes = {
        node.attr
        for rel, tree in trees.items()
        if rel != settings_rel
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }

    loaded = _settings_vars(trees[settings_rel])
    unknown = sorted(set(settings_module.DEPRECATED_ENV_VARS) - set(loaded))
    if unknown:
        raise ExtractionError(
            f"DEPRECATED_ENV_VARS names variables settings.py never loads: {unknown}"
        )
    values: dict[str, dict[str, Any]] = {}
    for name, info in loaded.items():
        value = {k: v for k, v in info.items() if k != "attribute"}
        value["source"] = f"pyeye/{settings_rel}"
        value.update(_status(name, info["attribute"], used_attributes))
        values[name] = value
    for module, tree in trees.items():
        if module == settings_rel:
            continue
        for name, default in _direct_reads(tree, module).items():
            values.setdefault(
                name,
                {"type": "str", "default": default, "source": f"pyeye/{module}", "status": "live"},
            )

    facts = [Fact(f"env.{name}", values[name], code(name)) for name in sorted(values)]
    yield from facts
    headers = ["Variable", "Default", "Range", "Status"]
    yield view("env.all", facts, table(headers, [_row(f) for f in facts]))
    deprecated = [f for f in facts if f.value["status"] == "deprecated"]
    yield view("env.deprecated", deprecated, table(headers, [_row(f) for f in deprecated]))
    # A default, inline in prose ("default <block>0.5</block> s"): D12 wants a
    # documented default bound to the code, not restated.
    for fact in facts:
        yield view(f"{fact.id}.default", [fact], literal(fact.value["default"]))
