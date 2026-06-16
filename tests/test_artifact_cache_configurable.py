"""The artifact cache cap is configurable (settings-driven default).

Follows from the #397 investigation: the AST/Script cache cap (formerly a
hardcoded 500 shared between AST and Script stores) is the cheapest lever for
large repos, so it must be tunable without code changes.
"""

from __future__ import annotations

from pyeye import (
    file_artifact_cache,
    settings as settings_mod,
)


def test_default_cap_follows_settings(monkeypatch):
    """FileArtifactCache() with no argument uses the configured cap."""
    monkeypatch.setattr(settings_mod.settings, "artifact_cache_max_entries", 1234)
    cache = file_artifact_cache.FileArtifactCache()
    assert cache._ast_max_entries == 1234


def test_explicit_cap_overrides_settings(monkeypatch):
    """An explicit constructor argument still wins (test isolation, tuning)."""
    monkeypatch.setattr(settings_mod.settings, "artifact_cache_max_entries", 1234)
    cache = file_artifact_cache.FileArtifactCache(ast_max_entries=7)
    assert cache._ast_max_entries == 7
