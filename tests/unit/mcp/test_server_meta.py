"""Tests for the server-level in-band feedback surface (#458).

Two surfaces are wired into the FastMCP server:

* the ``instructions`` block (always in the agent's context after initialize),
* the ``pyeye://about`` resource (deterministic version + repo + issues fetch).
"""

from __future__ import annotations

import json

import pyeye.mcp.meta as meta
from pyeye.mcp.server import get_about, mcp


class TestServerInstructions:
    """The FastMCP server is constructed with the #458 instructions block."""

    def test_server_carries_instructions(self) -> None:
        assert mcp.instructions == meta.server_instructions()

    def test_instructions_name_the_issues_url(self) -> None:
        assert meta.issues_url() in (mcp.instructions or "")


class TestAboutResource:
    """``pyeye://about`` returns the version + repo + issues pointer payload."""

    def test_about_resource_returns_metadata(self) -> None:
        payload = json.loads(get_about())
        assert payload == meta.about()

    def test_about_resource_includes_issues_url(self) -> None:
        assert meta.issues_url() in get_about()
