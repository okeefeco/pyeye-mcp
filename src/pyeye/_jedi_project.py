"""The one place pyeye builds a ``jedi.Project`` (#722).

This module is underscore-private (internal use only).  Do NOT export from
``pyeye/__init__.py``.

Jedi reports the base ``sys.path`` of its inference subprocess, and that
process runs a script from Jedi's own package
(``jedi/inference/compiled/subprocess/__main__.py``), so ``sys.path[0]`` is
that private directory.  Every file in it (``__init__.py``, ``functions.py``,
``__main__.py``) then reads as an importable top-level module, and, being
first, it shadows a same-named module that sits later on the path (a ``src/``
layout, a configured package).

:func:`make_project` passes Jedi an explicit base ``sys_path``: the
environment's own, in order, minus entries under Jedi's package directory.  An
explicit ``sys_path`` replaces only Jedi's *base* path, so ``smart_sys_path``
(the project root and its discovered parents) and ``added_sys_path`` still
apply on top, exactly as before.

The interpreter and the base path (#993): Jedi always runs pyeye's OWN
interpreter (never Jedi's default, which follows ``VIRTUAL_ENV`` and so ran an
activated environment's Python), and its base path is that interpreter's
standard library only, followed by the project environment's import roots
(:mod:`pyeye.environment`). pyeye's own ``site-packages`` is never on it, so a
project's imports can't resolve against pyeye's dependencies.
"""

from __future__ import annotations

import functools
import logging
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import jedi
from jedi.api.environment import InterpreterEnvironment, SameEnvironment

from pyeye.path_utils import normalize_path, relative_within

logger = logging.getLogger(__name__)

_JEDI_DIR = normalize_path(jedi.__file__).parent


def is_jedi_private_path(entry: str) -> bool:
    """Whether a ``sys.path`` *entry* lies inside Jedi's own package directory."""
    if not entry:
        return False
    try:
        return relative_within(entry, _JEDI_DIR) is not None
    except (OSError, ValueError):
        return False


#: Whether Jedi may load compiled extension modules from outside the environment's
#: own ``sys.path`` (the analysed project, configured packages). Loading one runs
#: its native code, so it stays off (docs fact ``security.jedi_unsafe_extensions``).
LOAD_UNSAFE_EXTENSIONS = False


@functools.cache
def own_environment() -> Any:
    """Jedi's environment for pyeye's OWN interpreter, one per process (#993).

    Jedi's default follows ``VIRTUAL_ENV`` / ``CONDA_PREFIX`` and would run that
    environment's Python; the project environment is read statically instead
    (:mod:`pyeye.environment`). One instance, so every project shares one
    inference subprocess, as Jedi's cached default did.
    """
    try:
        return SameEnvironment()
    except Exception as exc:  # e.g. an embedded interpreter: Jedi's own fallback
        logger.debug("own_environment: SameEnvironment unavailable: %s", exc)
        return InterpreterEnvironment()


def _is_stdlib_entry(entry: str) -> bool:
    """Whether *entry* is the interpreter's own library: under ``sys.base_prefix``, not site-packages."""
    from pyeye.scope import _has_site_packages_segment

    try:
        return relative_within(entry, sys.base_prefix) is not None and not (
            _has_site_packages_segment(Path(entry))
        )
    except (OSError, ValueError):
        return False


#: Whether Jedi still has the private hook :func:`_filter_walk` wraps (#1079).
#: Verified against Jedi 0.20.1; without it, the walk is left as is, with a warning.
_HAS_SYS_PATH_HOOK = callable(getattr(jedi.Project, "_get_sys_path", None))


def _filter_walk(project: Any) -> None:
    """Make *project*'s smart sys-path walk never add a directory inside an import root (#1079).

    Jedi's ``smart_sys_path`` (``jedi.Project._get_sys_path``) walks up from the
    analysed file, skipping directories with an ``__init__.py``, and appends the
    first one without. Inside a PEP 420 namespace under ``src`` that is the
    namespace directory itself (``src/poetry``). On ``sys.path`` it makes every
    module in it a top-level one: ``src/poetry/poetry.py`` then answers ``import
    poetry`` as a regular module, which beats the namespace package in ``src``,
    so no ``poetry.*`` import resolves from a file in the namespace.

    A directory strictly inside one of the project's import roots (its
    ``added_sys_path``: ``src``, configured packages, namespace roots) is part of
    a package, never an import root of its own, so such a walk entry is dropped
    (:func:`_without_inner_walk_entries`). A flat layout, whose import root is
    the project itself, is unchanged.

    Installed on the instance, wrapping the class's own method, so Jedi's
    per-inference-state cache still runs and a ``jedi.Project`` patched in tests
    stays patchable. Marked ``__pyeye_import_roots__`` for the tests that pin it.
    """
    original = getattr(type(project), "_get_sys_path", None)
    if not callable(original):
        return  # a test double, or a Jedi without the hook (warned at import)

    def _get_sys_path(  # type: ignore[no-untyped-def]
        inference_state, add_parent_paths=True, add_init_paths=False
    ):
        paths = original(
            project,
            inference_state,
            add_parent_paths=add_parent_paths,
            add_init_paths=add_init_paths,
        )
        return _without_inner_walk_entries(paths, project)

    _get_sys_path.__pyeye_import_roots__ = True  # type: ignore[attr-defined]
    project._get_sys_path = _get_sys_path


def _without_inner_walk_entries(paths: list[str], project: Any) -> list[str]:
    """*paths* minus the walk entries strictly inside one of *project*'s import roots (#1079)."""
    root = Path(project.path)
    added = [Path(p) for p in project.added_sys_path]
    roots = [r for r in added if relative_within(r, root) != Path(".")]
    if not roots:
        return paths
    explicit = {Path(p) for p in (getattr(project, "_sys_path", None) or [])}
    explicit.update(added)
    explicit.add(root)
    kept = []
    for entry in paths:
        candidate = Path(entry)
        if candidate not in explicit and any(
            (inside := relative_within(candidate, r)) is not None and inside.parts for r in roots
        ):
            logger.debug("Jedi sys.path: dropping %s, inside an import root (#1079)", entry)
            continue
        kept.append(entry)
    return kept


def make_project(
    path: str | Path,
    added_sys_path: Iterable[str] = (),
    environment_paths: Iterable[str] = (),
) -> jedi.Project:
    """Build a ``jedi.Project`` on pyeye's own interpreter and an explicit base ``sys.path``.

    Args:
        path: The Jedi project root.
        added_sys_path: Extra paths Jedi appends after the base path (configured
            packages and namespace roots), passed through unchanged.
        environment_paths: The project environment's import roots
            (``ProjectEnvironment.site_paths``, #993), after the standard library.

    Returns:
        The project, built with one ``jedi.Project`` call, whose smart
        sys-path walk never adds a directory inside an import root
        (:func:`_filter_walk`, #1079). Its base path is the
        interpreter's standard library (minus Jedi's own directory, #722), then
        *environment_paths*; pyeye's own ``site-packages`` is never on it. If the
        interpreter's path can't be read, the base is *environment_paths* alone
        rather than failing analysis.
    """
    kwargs: dict[str, Any] = {
        "path": Path(path).as_posix(),
        "load_unsafe_extensions": LOAD_UNSAFE_EXTENSIONS,
    }
    added = list(added_sys_path)
    if added:  # Jedi's own default otherwise; it doesn't accept None
        kwargs["added_sys_path"] = added
    environment = own_environment()
    try:
        base = environment.get_sys_path()
    except Exception as exc:  # never fail analysis over the filter
        logger.debug("make_project: interpreter sys.path unavailable: %s", exc)
        base = []
    stdlib = [p for p in base if p and not is_jedi_private_path(p) and _is_stdlib_entry(p)]
    kwargs["sys_path"] = list(dict.fromkeys([*stdlib, *environment_paths]))
    project = jedi.Project(**kwargs)
    if _HAS_SYS_PATH_HOOK:
        _filter_walk(project)
    else:
        logger.warning(
            "jedi.Project._get_sys_path is gone: Jedi's smart sys.path walk is not filtered, "
            "so a module named like its own namespace can hide it (#1079)"
        )
    # The interpreter Jedi runs: pyeye's own, never Jedi's VIRTUAL_ENV-driven
    # default. get_environment() returns this cached attribute when it's set.
    project._environment = environment
    return project
