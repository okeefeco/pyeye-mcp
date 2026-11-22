"""A static extractor gives exactly what its import-based twin gives (#1098).

The static ``extract`` must yield the same facts and views, in the same order,
as ``_extract_imported`` on this repository. Each extractor was proven this way
before its import path was deleted. ``edges`` and ``scopes`` keep the twin: the
server still fills its tool descriptions from the live constants (#1098 Q1), so
this test holds the server's self-description equal to the docs' static facts.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import pytest

from pyeye.docs_facts import extractors

ROOT = Path(__file__).resolve().parents[1]

TWINS = [
    name
    for info in pkgutil.iter_modules(extractors.__path__)
    if hasattr(
        importlib.import_module(name := f"{extractors.__name__}.{info.name}"), "_extract_imported"
    )
]


@pytest.mark.parametrize("module", TWINS)
def test_static_equals_imported(module: str) -> None:
    extractor = importlib.import_module(module)
    assert list(extractor.extract(ROOT)) == list(extractor._extract_imported(ROOT))
