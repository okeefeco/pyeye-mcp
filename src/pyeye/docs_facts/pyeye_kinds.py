"""pyeye's own extractors as built-in kinds, ``pyeye-*``, for pyeye's repository only (#1107).

pyeye's config names its extractors the way any repository names a built-in
kind (:mod:`.kinds`), so it needs no preset. Each extractor reads pyeye's own
source by pyeye's own conventions, so no generic kind can express it yet; each
kind's docstring says why. #1119 converts them to generic kinds and counts how
many remain.

**Restricted.** A ``pyeye-*`` kind runs only on pyeye's own repository: the one
whose ``pyproject.toml`` declares ``[project] name = "pyeye-mcp"``
(:data:`PROJECT_NAME`). The package name is what PyPI and the lockfile key on,
so a fork or checkout of pyeye still has it, and a repository can't match by
accident. Anywhere else, extraction stops with an
:class:`~.facts.ExtractionError` naming the restriction. A kind takes no
options.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from .. import _data_files
from .extractors import (
    ci,
    duplication,
    edges,
    env,
    mcp_surface,
    repo_config,
    resolver,
    review,
    scopes,
    security,
)
from .facts import Bindable, ExtractionError, KindOptionsError
from .registry import Extractor

#: The ``[project] name`` that marks pyeye's own repository.
PROJECT_NAME = "pyeye-mcp"

#: Every ``pyeye-*`` kind's name starts with this.
PREFIX = "pyeye-"

#: How many ``pyeye-*`` kinds remain: #1119's measure of how fully pyeye
#: dogfoods docs-facts. It must equal ``len(PYEYE_KINDS)`` (a test checks), and
#: the docs-facts dev doc shows it as the ``docs_facts.pyeye_kinds_remaining`` fact.
#: It started at 11 (#1107); ``pyeye-cli`` became ``entry-points``.
REMAINING = 10


def project_name(root: Path) -> str | None:
    """``[project] name`` in *root*'s ``pyproject.toml``, or ``None`` if it has none."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    name = _data_files.read_toml(pyproject).get("project", {}).get("name")
    return name if isinstance(name, str) else None


def _restricted(kind: str, extract: Callable[[Path], Iterable[Bindable]]) -> Callable[..., Any]:
    def run(root: Path) -> Iterable[Bindable]:
        found = project_name(root)
        if found != PROJECT_NAME:
            declared = f"declares {found!r}" if found else "declares no [project] name"
            raise ExtractionError(
                f"kind {kind!r} is restricted to pyeye's own repository, the one whose "
                f'pyproject.toml declares [project] name = "{PROJECT_NAME}"; this one '
                f"{declared}. It reads pyeye's source by pyeye's conventions (#1107, #1119)."
            )
        return extract(root)

    return run


def _kind(module: Any, name: str, why: str) -> tuple[str, Callable[[Mapping[str, Any]], Extractor]]:
    kind = PREFIX + name.replace("_", "-")

    def factory(options: Mapping[str, Any]) -> Extractor:
        if options:
            raise KindOptionsError(f"{kind!r} takes no options; got {sorted(options)}")
        return Extractor(name, tuple(module.PREFIXES), _restricted(kind, module.extract))

    summary = (module.__doc__ or "").split("\n", 1)[0]
    factory.__name__ = factory.__qualname__ = kind.replace("-", "_")
    factory.__doc__ = f"{summary}\n\nNo generic kind can express it: {why}"
    return kind, factory


#: Every ``pyeye-*`` kind, in the order pyeye's registry runs them. ``pyeye-cli``
#: became the generic ``entry-points`` kind (#1119, :mod:`.entry_points`).
PYEYE_KINDS: dict[str, Callable[[Mapping[str, Any]], Extractor]] = dict(
    (
        _kind(
            mcp_surface,
            "mcp_surface",
            "the tools are found through pyeye's registration conventions (the "
            "``@mcp.tool()`` functions, ``ADMIN_TOOLS`` and each plugin class's "
            "``register_tools()`` dict, plus the parameters the server declares it adds), "
            "and their annotations are rendered as MCP schema types.",
        ),
        _kind(
            edges,
            "edges",
            "each edge's status is a classification across several declared sets "
            "and its ceiling and determinism come from further tables; a literal fact "
            "reads one constant, not a join of them.",
        ),
        _kind(
            env,
            "env",
            "the variables are found by scanning every module for pyeye's settings "
            "calls and ``os.environ`` reads, and a variable's status needs a second "
            "scan for its use (#556).",
        ),
        _kind(
            ci,
            "ci",
            "each fact is checked against other files (every workflow's threshold "
            "agrees, the matrix equals the classifiers), and ``ci.yml`` is read by "
            "pattern; a data fact reads one key and checks nothing.",
        ),
        _kind(
            review,
            "review",
            "it joins four dicts keyed by ``SEED_AXES`` (descriptions, facets, stakes "
            "bucket and prior) with the ``_TIER`` grades, and one view is ordered by a "
            "further table, ``_BUCKET_ORDER``. A generic kind's schema is fixed under a "
            "prefix (#1119); a join like this would need a template vocabulary.",
        ),
        _kind(
            duplication,
            "duplication",
            "the command vocabulary, flags, defaults, thresholds and dismissal "
            "reasons come from several declarations in ``pyeye.duplication``.",
        ),
        _kind(
            scopes,
            "scopes",
            "one ``ScopeForm(...)`` call table gives two fact shapes (each form "
            "shows its syntax, not its key, in a list view and a table view), plus a policy "
            "fact joining a fixed order with a constant. The server also renders these "
            "facts live (``describe.live_facts``). A generic call-table kind would need "
            "ID, markdown and view templates, which #1119 ruled out.",
        ),
        _kind(
            security,
            "security",
            "the server modules are the import closure of pyeye's MCP entry point, "
            "and the subprocess, write and network sites are found by walking them.",
        ),
        _kind(
            resolver,
            "resolver",
            "three ``Step(...)`` call tables merge into one positioned family, each "
            "table adding its side (all, project or external), with a numbered view that "
            "has a heading per table, beside the ``NameRule(...)`` policy. A generic "
            "call-table kind would need ID, markdown and view templates, which #1119 "
            "ruled out.",
        ),
        _kind(
            repo_config,
            "repo_config",
            "the pre-commit hooks are read by pattern with a consistency rule (every "
            "``uv run`` hook passes the same flags), beside pyeye's config key tables.",
        ),
    )
)
