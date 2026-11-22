"""Repository configuration facts: pre-commit hooks and the pyeye config's names (#830, C17).

C17: a value in a committed machine-readable file that a doc states is a fact.

- ``precommit.hook.<id>``: each hook in ``.pre-commit-config.yaml``, in file
  order, with the ``repo`` it comes from as its value. The file is read with a pattern, not a YAML parser, so no dependency is
  added (as :mod:`.ci` reads ``ci.yml``); a file with no hook ids fails loudly.
- ``precommit.uv_run_flags``: the flags every hook entry that runs ``uv run``
  passes. One without them fails extraction: the hooks run one way.
- ``config.key.<key>``: the top-level config keys pyeye reads
  (:data:`pyeye.config.CONFIG_KEYS`).
- ``config.ignored_key.<key>``: the keys pyeye ignores with a warning
  (:data:`pyeye.config.IGNORED_TOP_LEVEL_KEYS`).
- ``config.files.project`` / ``config.files.global`` / ``config.files.override``:
  the config file names, from :mod:`pyeye.constants`, each list in the order
  pyeye tries it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .. import static
from ..facts import Bindable, ExtractionError, Fact, code, code_list, view

PREFIXES = ("precommit", "config")

PRE_COMMIT_CONFIG = ".pre-commit-config.yaml"
_HOOK = re.compile(r"^\s*-\s+id:\s*([A-Za-z0-9_.-]+)\s*$", re.MULTILINE)
_UV_RUN_ENTRY = re.compile(r"^\s*entry:\s*uv run((?:\s+--?[A-Za-z][\w-]*)*)", re.MULTILINE)
_FLAG = re.compile(r"--?[A-Za-z][\w-]*")


_REPO = re.compile(r"^\s*-\s+repo:\s*(\S+)\s*$")


def hook_ids(text: str) -> list[str]:
    """The hook ids in a pre-commit config's text, in file order, each once."""
    return list(hook_repos(text))


def hook_repos(text: str) -> dict[str, str]:
    """Hook id -> the ``repo`` it comes from (``local`` or a URL), in file order.

    A hook id that appears twice keeps its first repo.
    """
    repos: dict[str, str] = {}
    repo = ""
    for line in text.splitlines():
        if m := _REPO.match(line):
            repo = m.group(1)
        elif m := _HOOK.match(line):
            repos.setdefault(m.group(1), repo)
    return repos


def uv_run_flags(text: str) -> list[str]:
    """The flags every ``entry: uv run …`` hook in a pre-commit config's text passes."""
    runs = [set(_FLAG.findall(m.group(1))) for m in _UV_RUN_ENTRY.finditer(text)]
    if not runs:
        raise ExtractionError(f"{PRE_COMMIT_CONFIG} has no `uv run` hook entry")
    common = sorted(set.intersection(*runs))
    if not common:
        raise ExtractionError(f"{PRE_COMMIT_CONFIG}'s `uv run` hooks share no flag")
    return common


def _items(prefix: str, names: tuple[str, ...]) -> list[Fact]:
    return [Fact(f"{prefix}.{name}", name, code(name)) for name in names]


def extract(root: Path) -> Iterator[Bindable]:
    """Yield the pre-commit hook and pyeye config facts, plus their views.

    The config constants are read from the source, never imported (#1098, C19).
    """
    return _facts(root, static.Module(root, "pyeye.config"), static.Module(root, "pyeye.constants"))


def _facts(root: Path, config: Any, constants: Any) -> Iterator[Bindable]:
    text = (root / PRE_COMMIT_CONFIG).read_text(encoding="utf-8")
    repos = hook_repos(text)
    if not repos:
        raise ExtractionError(f"{PRE_COMMIT_CONFIG} lists no hook ids")
    hooks = list(repos)
    # A structured value: the hook id is the fact's name, its repo the value.
    hook_facts = [
        Fact(f"precommit.hook.{hook}", {"repo": repo}, code(hook)) for hook, repo in repos.items()
    ]
    yield from hook_facts
    yield view("precommit.hooks", hook_facts, code_list(hooks))
    flags = uv_run_flags(text)
    yield Fact("precommit.uv_run_flags", flags, " ".join(code(f) for f in flags))

    keys = _items("config.key", config.CONFIG_KEYS)
    yield from keys
    yield view("config.keys", keys, code_list(config.CONFIG_KEYS))

    ignored = _items("config.ignored_key", config.IGNORED_TOP_LEVEL_KEYS)
    yield from ignored
    yield view("config.ignored_keys", ignored, code_list(config.IGNORED_TOP_LEVEL_KEYS))

    project = Fact(
        "config.files.project", list(constants.CONFIG_FILES), code_list(constants.CONFIG_FILES)
    )
    global_ = Fact(
        "config.files.global",
        list(constants.GLOBAL_CONFIG_FILES),
        code_list(f"~/{name}" for name in constants.GLOBAL_CONFIG_FILES),
    )
    override = Fact("config.files.override", constants.OVERRIDE_FILE, code(constants.OVERRIDE_FILE))
    yield from (project, global_, override)
