"""In-band self-description and feedback surface for the PyEye MCP server.

Issue #458: when an agent (or its supervisor) hits a pyeye limitation mid-session,
there must be an *in-band* pointer to where a bug can be reported — the agent
should never have to guess the repo slug.  This module is the single source for
that pointer (repository + issues URL + version).

Single source of truth
-----------------------
The URLs live in ``pyproject.toml``'s ``[project.urls]`` and are read here from
installed package metadata, so the pointer can never drift from the canonical
project metadata.  When the distribution metadata is unavailable (e.g. running
straight from a source tree without an install), we fall back to the canonical
slug rather than raising — a feedback pointer must always be available.
"""

from __future__ import annotations

from importlib.metadata import PackageMetadata, PackageNotFoundError, metadata

from .. import __version__

# Distribution name (``[project] name`` in pyproject.toml — NOT the import name).
_DIST_NAME = "pyeye-mcp"

# Canonical fallbacks, used only when package metadata cannot be read.  Kept in
# sync with ``[project.urls]`` by the meta tests, which assert these exact values.
_FALLBACK_REPO_URL = "https://github.com/okeefeco/pyeye-mcp"
_FALLBACK_ISSUES_URL = f"{_FALLBACK_REPO_URL}/issues"


def _dist_metadata() -> PackageMetadata:
    """Return the installed distribution metadata (seam for tests to fault-inject)."""
    return metadata(_DIST_NAME)


def _project_url(label: str, fallback: str) -> str:
    """Return the ``Project-URL`` entry for *label*, or *fallback* if unavailable.

    ``Project-URL`` values are formatted ``"<Label>, <url>"``; we match *label*
    case-insensitively and return the URL portion.
    """
    try:
        md = _dist_metadata()
    except PackageNotFoundError:
        return fallback
    for entry in md.get_all("Project-URL") or []:
        name, _, url = str(entry).partition(",")
        if name.strip().lower() == label.lower():
            return url.strip()
    return fallback


def repo_url() -> str:
    """Canonical repository URL for reporting/inspecting pyeye itself."""
    return _project_url("Repository", _FALLBACK_REPO_URL)


def issues_url() -> str:
    """Canonical issues URL — where to report a bug about pyeye."""
    return _project_url("Issues", _FALLBACK_ISSUES_URL)


def version() -> str:
    """Return the installed pyeye version string (``0.0.0+unknown`` if uninstalled)."""
    return __version__


def about() -> dict[str, str]:
    """Flat, deterministic self-description payload for an agent to fetch.

    Answers "what version are you, and how do I report a problem with you?" in
    one round-trip — pointers only, no source content.
    """
    return {
        "name": "pyeye",
        "version": version(),
        "repository": repo_url(),
        "issues": issues_url(),
    }


def server_instructions() -> str:
    """MCP ``instructions`` block — sent to the client at initialize.

    Surfaces the issues URL so the feedback path is always in the agent's
    context, not something it has to discover out-of-band (#458).
    """
    return (
        "PyEye provides semantic Python code intelligence (resolve / resolve_at / "
        "inspect / outline / expand / trace) over canonical handles. It returns "
        "structured pointers and facts, never source content.\n\n"
        "Found a bug or limitation in pyeye itself? Report it at "
        f"{issues_url()} . The pyeye://about resource returns the version and "
        "these URLs deterministically."
    )
