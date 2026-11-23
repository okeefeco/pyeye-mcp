"""The ``entry-points`` kind: a repository's console scripts and ``python -m`` modules (#1119).

A generic built-in kind (:mod:`.kinds`), for any repository. It replaced
``pyeye-cli``, and pyeye's config names it like any other::

    [[tool.pyeye.docs_facts.extractors]]
    kind = "entry-points"
    package = "src/acme"   # optional: where to look for __main__.py
    module = "acme"        # optional: the package's import name (default: the
                           # directory's name)
    prefix = "cli"         # optional: the facts' first ID segment (default "cli")

The facts, under *prefix*:

- ``<prefix>.script.<name>``: each console script in ``[project.scripts]`` of
  the repository's ``pyproject.toml``, sorted by name; its value is
  ``{"target": "<module>:<function>"}``.
- ``<prefix>.module.<dotted>``: each package under *package* (itself included)
  that holds a ``__main__.py``, so ``python -m <dotted>`` runs it; its value is
  ``{"command": "python -m <dotted>"}``. Without *package*, there are none.
- ``<prefix>.all``: a view tabling both, scripts first.

The files are read, never imported or run (C19). A missing ``pyproject.toml``
or ``[project]`` table, or a *package* that isn't a directory inside the
repository, is an :class:`~.facts.ExtractionError`, never an empty family.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import _data_files
from ..async_utils import filtered_rglob
from ..path_utils import relative_within
from .facts import Bindable, ExtractionError, Fact, code, table, view

if TYPE_CHECKING:
    from .registry import Extractor

#: The name a config's ``kind`` uses.
KIND = "entry-points"
#: The default first ID segment.
DEFAULT_PREFIX = "cli"
_OPTIONS = frozenset({"package", "module", "prefix"})


def _option(options: Mapping[str, Any], name: str) -> str | None:
    from .kinds import KindOptionsError

    value = options.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise KindOptionsError(f"{name!r} must be a non-empty string; got {value!r}")
    return value


def factory(options: Mapping[str, Any]) -> Extractor:
    """An ``entry-points`` extractor from its config options.

    Raises:
        KindOptionsError: On an unknown option, a non-string one, a *prefix*
            that isn't one ID segment, or a *module* without a *package*.
    """
    # Imported here: the registry builds pyeye's own extractor from this kind.
    from .kinds import KindOptionsError
    from .registry import Extractor

    unknown = sorted(set(options) - _OPTIONS)
    if unknown:
        raise KindOptionsError(f"unknown option(s) {unknown}; known: {sorted(_OPTIONS)}")
    package = _option(options, "package")
    module = _option(options, "module")
    prefix = _option(options, "prefix") or DEFAULT_PREFIX
    if "." in prefix:
        raise KindOptionsError(f"'prefix' must be one ID segment; got {prefix!r}")
    if module is not None and package is None:
        raise KindOptionsError("'module' needs 'package': it names that package")

    def extract(root: Path) -> Iterator[Bindable]:
        return _facts(root, prefix, package, module)

    return Extractor(prefix, (prefix,), extract)


def _scripts(root: Path) -> dict[str, str]:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        raise ExtractionError(f"{KIND}: {root.as_posix()} has no pyproject.toml")
    project = _data_files.read_toml(pyproject).get("project")
    if not isinstance(project, dict):
        raise ExtractionError(f"{KIND}: pyproject.toml has no [project] table")
    scripts = project.get("scripts", {})
    if not isinstance(scripts, dict) or not all(isinstance(t, str) for t in scripts.values()):
        raise ExtractionError(f"{KIND}: [project.scripts] must be a table of strings")
    return scripts


def _modules(root: Path, package: str, module: str | None) -> list[str]:
    directory = root / package
    if relative_within(directory, root) is None:
        raise ExtractionError(f"{KIND}: package {package!r} is outside the repository")
    if not directory.is_dir():
        raise ExtractionError(f"{KIND}: package {package!r} isn't a directory")
    name = module or directory.name
    found = []
    for main in sorted(filtered_rglob("__main__.py", directory)):
        rel = relative_within(main.parent, directory)
        if rel is not None:
            found.append(".".join((name, *rel.parts)))
    return found


def _facts(root: Path, prefix: str, package: str | None, module: str | None) -> Iterator[Bindable]:
    scripts = [
        Fact(f"{prefix}.script.{name}", {"target": target}, code(name))
        for name, target in sorted(_scripts(root).items())
    ]
    modules = []
    for dotted in _modules(root, package, module) if package is not None else []:
        command = f"python -m {dotted}"
        modules.append(Fact(f"{prefix}.module.{dotted}", {"command": command}, code(command)))
    yield from scripts
    yield from modules
    module_id = len(f"{prefix}.module.")
    rows = [[s.markdown, "console script", code(s.value["target"])] for s in scripts]
    rows += [[m.markdown, "module", code(m.id[module_id:])] for m in modules]
    yield view(f"{prefix}.all", [*scripts, *modules], table(["Command", "Kind", "Runs"], rows))
