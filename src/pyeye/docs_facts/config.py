"""A repository's docs-facts config: data only, never code (#1091, RFC #1083 step 1).

Where: ``[tool.pyeye.docs_facts]`` in ``pyproject.toml``, or ``"docs_facts"`` in
``.pyeye.json``, which wins. Only the repository's own files are read, never
the user's global pyeye config: docs facts describe one repository.

What (the maintainer's rulings via designer, 2026-11-22, and C19, no runtime
facts): every key is data, and nothing names code to import. A value shaped
like an import reference (``package.module:attr``) is refused wherever it
appears. The keys:

- ``facts``: a list of ``{id, from, file, key | name}`` tables, ``from`` one
  of the built-in kinds (:mod:`.data_facts`): ``toml``/``json``/``yaml`` read a
  dotted ``key``, ``literal`` a Python constant's ``name``;
- ``extractors``: a list of ``{kind, <options>}`` tables, ``kind`` a built-in
  kind (:data:`~.kinds.BUILT_IN_KINDS`), the rest its options;
- ``docs``: a list of ``{path, audience, kind, allow?, covers?, site?}`` tables,
  the doc registry (:class:`~.docs.DocEntry`);
- ``rules``: ``"all"`` (the default) or a list of rule IDs (:data:`~.rules.RULES`);
- ``changelog``: the changelog's path; absent turns release-dependent behaviour off;
- ``paths``: ``{snapshot, removed, uncovered, review_state}``, each defaulting to
  today's ``docs/facts/...`` file, and ``snapshots``, a table giving a fact
  family its own snapshot file (:class:`~.setup.Paths`, #1108);
- ``reference_only``: fact families that are reference data, kept out of the
  uncovered-fact ledger (#1108).

No config is an error: there is nothing to check.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import MappingProxyType
from typing import Any, get_args

from .. import _data_files
from ..path_utils import relative_within
from . import data_facts, kinds, rules
from .docs import Audience, DocEntry, Kind
from .facts import check_families
from .setup import Paths, Setup

SECTION = "docs_facts"
KEYS = frozenset({"facts", "extractors", "docs", "rules", "changelog", "paths", "reference_only"})
_FACT_KEYS = frozenset({"id", "from", "file", "key", "name"})
_DOC_KEYS = frozenset({"path", "audience", "kind", "allow", "covers", "site"})
_PATH_KEYS = frozenset(Paths.__dataclass_fields__)
#: ``package.module:attr``: the shape of a code reference, refused anywhere.
_CODE_REF = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_][\w.]*$")


class ConfigError(ValueError):
    """The repository's docs-facts config is missing or isn't valid data."""


def find(root: Path) -> dict[str, Any] | None:
    """The raw ``docs_facts`` section, from ``.pyeye.json`` first, then ``pyproject.toml``."""
    json_file = root / ".pyeye.json"
    if json_file.is_file():
        data = _data_files.read_json(json_file)
        if isinstance(data, dict) and SECTION in data:
            return _table(data[SECTION], f".pyeye.json {SECTION!r}")
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        section = _data_files.read_toml(pyproject).get("tool", {}).get("pyeye", {})
        if SECTION in section:
            return _table(section[SECTION], f"[tool.pyeye.{SECTION}]")
    return None


def load(root: Path) -> Setup:
    """The repository's :class:`~.setup.Setup`, built from its config.

    Raises:
        ConfigError: If there is no config, or it isn't valid.
    """
    raw = find(root)
    if raw is None:
        raise ConfigError(
            f"nothing to check: {root.as_posix()} has no [tool.pyeye.{SECTION}] in "
            f'pyproject.toml and no "{SECTION}" in .pyeye.json'
        )
    _refuse_code_refs(raw, SECTION)
    _only(raw, KEYS, SECTION)
    facts = tuple(_fact(entry, i, root) for i, entry in enumerate(_list(raw, "facts")))
    built = tuple(_kind(entry, i) for i, entry in enumerate(_list(raw, "extractors")))
    return Setup(
        extractors=((data_facts.extractor(facts),) if facts else ()) + built,
        docs=tuple(_doc(entry, i) for i, entry in enumerate(_list(raw, "docs"))),
        rules=_rules(raw.get("rules", "all")),
        pages={},
        changelog=_optional_str(raw, "changelog"),
        paths=_paths(raw.get("paths", {})),
        reference_only=_reference_only(raw.get("reference_only", [])),
    )


def _table(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a table")
    return value


def _list(raw: dict[str, Any], key: str) -> list[Any]:
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise ConfigError(f"{SECTION}.{key} must be a list of tables")
    return value


def _only(table: dict[str, Any], allowed: frozenset[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {unknown}; expected some of {sorted(allowed)}")


def _refuse_code_refs(value: Any, where: str) -> None:
    """Refuse any value shaped like ``package.module:attr``, at any depth (C19)."""
    if isinstance(value, str) and _CODE_REF.match(value):
        raise ConfigError(
            f"{where}: {value!r} looks like a code reference. docs-facts never imports "
            "or runs the analysed repository's code (C19): give facts as data."
        )
    if isinstance(value, dict):
        for key, item in value.items():
            _refuse_code_refs(item, f"{where}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _refuse_code_refs(item, f"{where}[{i}]")


def _str(table: dict[str, Any], key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where}: {key!r} must be a non-empty string")
    return value


def _optional_str(table: dict[str, Any], key: str) -> str | None:
    value = table.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{SECTION}.{key} must be a non-empty string")
    return value


def _fact(entry: Any, i: int, root: Path) -> data_facts.DataFact:
    where = f"{SECTION}.facts[{i}]"
    table = _table(entry, where)
    _only(table, _FACT_KEYS, where)
    kind = _str(table, "from", where)
    if kind not in data_facts.FACT_KINDS:
        raise ConfigError(f"{where}: 'from' must be one of {list(data_facts.FACT_KINDS)}")
    # A data file is read at a ``key`` path; a Python file's constant by its ``name``.
    field_name, other = ("name", "key") if kind == data_facts.LITERAL else ("key", "name")
    if other in table:
        raise ConfigError(f"{where}: a {kind!r} fact takes {field_name!r}, not {other!r}")
    fact_id = _str(table, "id", where)
    if "." not in fact_id:
        raise ConfigError(f"{where}: id {fact_id!r} needs a prefix (``prefix.name``)")
    file = _str(table, "file", where)
    if relative_within(root / file, root) is None:
        raise ConfigError(f"{where}: {file!r} is outside the repository")
    return data_facts.DataFact(fact_id, kind, file, _str(table, field_name, where))


def _kind(entry: Any, i: int) -> Any:
    """A built-in kind's extractor, built from its config table (:mod:`.kinds`)."""
    where = f"{SECTION}.extractors[{i}]"
    table = _table(entry, where)
    name = _str(table, "kind", where)
    factory = kinds.BUILT_IN_KINDS.get(name)
    if factory is None:
        raise ConfigError(
            f"{where}: kind {name!r} isn't built in; known: {sorted(kinds.BUILT_IN_KINDS)}"
        )
    options = MappingProxyType({k: v for k, v in table.items() if k != "kind"})
    try:
        return factory(options)
    except kinds.KindOptionsError as error:
        raise ConfigError(f"{where} ({name}): {error}") from error


def _doc(entry: Any, i: int) -> DocEntry:
    where = f"{SECTION}.docs[{i}]"
    table = _table(entry, where)
    _only(table, _DOC_KEYS, where)
    audience = _str(table, "audience", where)
    if audience not in get_args(Audience):
        raise ConfigError(f"{where}: audience {audience!r} isn't one of {list(get_args(Audience))}")
    kind = _str(table, "kind", where)
    if kind not in get_args(Kind):
        raise ConfigError(f"{where}: kind {kind!r} isn't one of {list(get_args(Kind))}")
    allow = table.get("allow", {})
    if not isinstance(allow, dict) or not all(
        isinstance(v, list) and all(isinstance(m, str) for m in v) for v in allow.values()
    ):
        raise ConfigError(f"{where}: 'allow' must map a rule ID to a list of messages")
    covers = table.get("covers", [])
    if not isinstance(covers, list) or not all(isinstance(c, str) for c in covers):
        raise ConfigError(f"{where}: 'covers' must be a list of fact IDs")
    site = table.get("site")
    if site is not None and not isinstance(site, bool):
        raise ConfigError(f"{where}: 'site' must be true or false")
    return DocEntry(
        _str(table, "path", where),
        audience,  # type: ignore[arg-type]
        kind,  # type: ignore[arg-type]
        MappingProxyType({rule: tuple(messages) for rule, messages in allow.items()}),
        tuple(covers),
        site,
    )


def _rules(value: Any) -> tuple[rules.Rule, ...]:
    if value == "all":
        return rules.RULES
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f'{SECTION}.rules must be "all" or a list of rule IDs')
    known = {r.id: r for r in rules.RULES}
    unknown = sorted(set(value) - set(known))
    if unknown:
        raise ConfigError(f"{SECTION}.rules: unknown rule(s) {unknown}; known: {sorted(known)}")
    return tuple(known[rule_id] for rule_id in value)


def _paths(value: Any) -> Paths:
    where = f"{SECTION}.paths"
    table = dict(_table(value, where))
    _only(table, _PATH_KEYS, where)
    snapshots = table.pop("snapshots", {})
    if not isinstance(snapshots, dict) or not all(
        isinstance(v, str) and v for v in snapshots.values()
    ):
        raise ConfigError(f"{where}.snapshots must be a table of fact family = file")
    for key in table:
        _str(table, key, where)
    try:
        return Paths(**table, snapshots=MappingProxyType(snapshots))
    except ValueError as error:
        raise ConfigError(f"{where}.{error}") from error


def _reference_only(value: Any) -> frozenset[str]:
    if not isinstance(value, list):
        raise ConfigError(f"{SECTION}.reference_only must be a list of fact families")
    try:
        check_families(value, f"{SECTION}.reference_only")
    except ValueError as error:
        raise ConfigError(str(error)) from error
    return frozenset(value)
