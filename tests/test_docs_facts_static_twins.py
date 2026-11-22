"""Each static extractor gives exactly what its import-based twin gave (#1098).

While both exist, the static ``extract`` must yield the same facts and views,
in the same order, as ``_extract_imported`` on this repository. The twins are
deleted once every extractor passes, and this test with them.
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
