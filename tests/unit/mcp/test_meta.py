"""Tests for ``pyeye.mcp.meta`` — the in-band self-description / feedback surface.

Issue #458: pyeye must expose, *in band*, where to report a bug about itself.
This module is the single source for that pointer (repo + issues URL + version),
read from installed package metadata so the URL never duplicates / drifts from
``pyproject.toml``'s ``[project.urls]`` (the source of truth).
"""

from __future__ import annotations

import pyeye.mcp.meta as meta


class TestUrls:
    """Repo / issues URLs resolve to the canonical okeefeco/pyeye-mcp slug."""

    def test_issues_url_points_at_github_issues(self) -> None:
        assert meta.issues_url() == "https://github.com/okeefeco/pyeye-mcp/issues"

    def test_repo_url_points_at_github_repo(self) -> None:
        assert meta.repo_url() == "https://github.com/okeefeco/pyeye-mcp"

    def test_urls_are_single_line_pointers(self) -> None:
        # Layering: these are pointers, never content — single-line, no newlines.
        for url in (meta.issues_url(), meta.repo_url()):
            assert "\n" not in url
            assert url.startswith("https://")


class TestVersion:
    """Version is a non-empty string (never raises, even when uninstalled)."""

    def test_version_is_nonempty_str(self) -> None:
        v = meta.version()
        assert isinstance(v, str)
        assert v


class TestAbout:
    """``about()`` is the deterministic payload an agent fetches to self-describe."""

    def test_about_carries_version_repo_and_issues(self) -> None:
        about = meta.about()
        assert about["name"] == "pyeye"
        assert about["version"] == meta.version()
        assert about["repository"] == meta.repo_url()
        assert about["issues"] == meta.issues_url()

    def test_about_is_flat_pointer_payload(self) -> None:
        # No content smuggling: every value is a single-line string.
        for value in meta.about().values():
            assert isinstance(value, str)
            assert "\n" not in value


class TestServerInstructions:
    """The MCP instructions block names the issues URL so it is always in context."""

    def test_instructions_mention_issues_url(self) -> None:
        instructions = meta.server_instructions()
        assert meta.issues_url() in instructions

    def test_instructions_are_nonempty(self) -> None:
        assert meta.server_instructions().strip()


class TestMetadataFallback:
    """URL resolution survives the not-installed case (no PackageNotFoundError)."""

    def test_urls_resolve_without_package_metadata(self, monkeypatch) -> None:
        from importlib.metadata import PackageNotFoundError

        def _boom() -> object:
            raise PackageNotFoundError

        monkeypatch.setattr(meta, "_dist_metadata", _boom)
        # Falls back to the hardcoded canonical slug rather than raising.
        assert meta.issues_url() == "https://github.com/okeefeco/pyeye-mcp/issues"
        assert meta.repo_url() == "https://github.com/okeefeco/pyeye-mcp"
