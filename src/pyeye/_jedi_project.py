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
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

import jedi

logger = logging.getLogger(__name__)

_JEDI_DIR = Path(jedi.__file__).resolve().parent


def is_jedi_private_path(entry: str) -> bool:
    """Whether a ``sys.path`` *entry* lies inside Jedi's own package directory."""
    if not entry:
        return False
    try:
        return Path(entry).resolve().is_relative_to(_JEDI_DIR)
    except (OSError, ValueError):
        return False


def make_project(path: str | Path, added_sys_path: Iterable[str] = ()) -> jedi.Project:
    """Build a ``jedi.Project`` whose base ``sys.path`` excludes Jedi's own directory.

    Args:
        path: The Jedi project root.
        added_sys_path: Extra paths Jedi appends after the base path (configured
            packages and namespace roots), passed through unchanged.

    Returns:
        The project.  If the environment's path can't be read, Jedi's default
        (unfiltered) base path is kept rather than failing analysis.
    """
    root = Path(path).as_posix()
    added = list(added_sys_path)
    project = jedi.Project(path=root, added_sys_path=added)
    try:
        base = [p for p in project.get_environment().get_sys_path() if p]
    except Exception as exc:  # never fail analysis over the filter
        logger.debug("make_project: environment sys.path unavailable: %s", exc)
        return project
    filtered = [p for p in base if not is_jedi_private_path(p)]
    return jedi.Project(path=root, added_sys_path=added, sys_path=filtered)
