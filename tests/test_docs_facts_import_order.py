"""Every ``pyeye.docs_facts`` module imports first, in a fresh interpreter (#1163).

``import pyeye.docs_facts.kinds`` once raised ImportError: ``kinds`` imported
``registry``, which built pyeye's ``cli`` extractor at import time through
``entry_points.factory``, which imported ``KindOptionsError`` from the
half-initialised ``kinds``. The suite stayed green because other modules were
always imported first. So each module gets an interpreter of its own here,
with nothing imported before it.
"""

from __future__ import annotations

import pkgutil
import subprocess  # nosec B404 - runs this interpreter with fixed arguments
import sys

import pytest

import pyeye.docs_facts


def _modules() -> list[str]:
    """Every module and subpackage under ``pyeye.docs_facts``, found on disk."""
    found = [pyeye.docs_facts.__name__]
    for info in pkgutil.walk_packages(pyeye.docs_facts.__path__, "pyeye.docs_facts."):
        if not info.name.endswith(".__main__"):  # running it is the entry point's test
            found.append(info.name)
    return sorted(found)


MODULES = _modules()


def test_the_walk_finds_the_modules_that_matter() -> None:
    for name in ("kinds", "registry", "entry_points", "pyeye_kinds", "config", "cli"):
        assert f"pyeye.docs_facts.{name}" in MODULES
    assert any(m.startswith("pyeye.docs_facts.extractors.") for m in MODULES)


@pytest.mark.parametrize("module", MODULES)
def test_it_imports_first(module: str) -> None:
    done = subprocess.run(  # nosec B603 - fixed arguments, this interpreter
        [sys.executable, "-c", f"import {module}"], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


def test_kind_options_error_is_one_class() -> None:
    """``kinds`` re-exports the leaf module's class, so either import catches it."""
    from pyeye.docs_facts import facts, kinds

    assert kinds.KindOptionsError is facts.KindOptionsError
    assert issubclass(kinds.KindOptionsError, ValueError)
