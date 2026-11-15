"""``PYEYE_CACHE_TTL`` drives the live analyzer cache (#628).

It used to size only ``GranularCache``, which nothing ever wrote to, while the
analyzer's ``ScopedCache`` was hard-coded to 300 s.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye import settings as settings_module
from pyeye.analyzers.jedi_analyzer import JediAnalyzer


@pytest.fixture()
def cache_ttl(monkeypatch: pytest.MonkeyPatch):
    def set_ttl(value: str) -> None:
        monkeypatch.setenv("PYEYE_CACHE_TTL", value)
        monkeypatch.setattr(settings_module, "settings", settings_module.PerformanceSettings())

    return set_ttl


def test_default_ttl_is_300(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYEYE_CACHE_TTL", raising=False)
    monkeypatch.setattr(settings_module, "settings", settings_module.PerformanceSettings())

    assert JediAnalyzer(tmp_path.as_posix()).scoped_cache.ttl == 300


def test_env_var_sets_the_scoped_cache_ttl(tmp_path: Path, cache_ttl) -> None:
    cache_ttl("42")

    assert JediAnalyzer(tmp_path.as_posix()).scoped_cache.ttl == 42


def test_zero_ttl_disables_scoped_caching(tmp_path: Path, cache_ttl) -> None:
    cache_ttl("0")
    cache = JediAnalyzer(tmp_path.as_posix()).scoped_cache

    cache.set("key", "value", "main")

    assert cache.get("key", "main") is None


def test_analyzer_no_longer_builds_unused_scope_helpers(tmp_path: Path) -> None:
    analyzer = JediAnalyzer(tmp_path.as_posix())

    for name in ("lazy_loader", "scope_debugger", "scope_validator"):
        assert not hasattr(analyzer, name), name
