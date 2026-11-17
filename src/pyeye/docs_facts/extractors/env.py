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
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ... import settings as settings_module
from ...async_utils import filtered_rglob
from ...path_utils import relative_within
from ..facts import Bindable, Fact, code, literal, table, view

PREFIXES = ("env",)

_KINDS = {"_get_int_env": "int", "_get_float_env": "float", "_get_bool_env": "bool"}


def _literal(node: ast.expr | None) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except ValueError:
        return None


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
        name = _literal(call.args[0])
        keywords = {k.arg: _literal(k.value) for k in call.keywords}
        found[name] = {
            "attribute": node.target.attr,
            "type": _KINDS[func.attr],
            "default": _literal(call.args[1]) if len(call.args) > 1 else None,
            "min": keywords.get("min_val"),
            "max": keywords.get("max_val"),
        }
    return found


def _is_environ(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "environ"


def _direct_reads(tree: ast.Module) -> dict[str, Any]:
    """``PYEYE_*`` name -> literal default, for each direct environment read."""
    found: dict[str, Any] = {}
    for node in ast.walk(tree):
        args: list[ast.expr] = []
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            func = node.func
            if (func.attr == "get" and _is_environ(func.value)) or func.attr == "getenv":
                args = list(node.args)
        elif isinstance(node, ast.Subscript) and _is_environ(node.value):
            args = [node.slice]
        name = _literal(args[0]) if args else None
        if isinstance(name, str) and name.startswith("PYEYE_"):
            found.setdefault(name, _literal(args[1]) if len(args) > 1 else None)
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

    values: dict[str, dict[str, Any]] = {}
    for name, info in _settings_vars(trees[settings_rel]).items():
        value = {k: v for k, v in info.items() if k != "attribute"}
        value["source"] = f"pyeye/{settings_rel}"
        value.update(_status(name, info["attribute"], used_attributes))
        values[name] = value
    for module, tree in trees.items():
        for name, default in _direct_reads(tree).items():
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
