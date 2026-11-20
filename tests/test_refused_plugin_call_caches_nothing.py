"""A refused plugin call leaves no cached plugin context behind (#1061).

``project_path="/"`` with ``scope="main"`` is refused (#856: "/" is an
ancestor of a restricted directory, so no scan starts there). The tool wrapper
used to build and cache a plugin context for "/" BEFORE the scan refused, so
the cache kept an entry for a project nothing was ever answered about, and a
later test counting cached contexts failed depending on file order.

A context is now built uncached and stored only when the call succeeds.
Django, Flask and Pydantic all go through the one wrapper (``_plugin_tool``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.path_utils import path_to_key
from pyeye.project_manager import get_project_manager
from tests.test_final_form_path_checks import _assert_refused, _ok, _plugin_server

pytestmark = pytest.mark.skipif(
    __import__("os").name == "nt", reason="'/' is the POSIX ancestor case"
)

TOOLS = ["find_pydantic_models", "find_django_models", "find_flask_routes"]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    return root


def _contexts_for(path: str | Path) -> list[tuple[str, type]]:
    key = path_to_key(path)
    return [k for k in get_project_manager()._plugin_contexts if k[0] == key]


@pytest.mark.parametrize("tool", TOOLS)
def test_a_refused_call_caches_no_context(project: Path, tool: str) -> None:
    server = _plugin_server(project)
    before = dict(get_project_manager()._plugin_contexts)

    _assert_refused(tool, {"scope": "main", "project_path": "/"}, server)

    assert _contexts_for("/") == []
    assert get_project_manager()._plugin_contexts == before


def test_a_successful_call_still_caches_one_context(project: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    (other / "pkg").mkdir(parents=True)
    (other / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    server = _plugin_server(project)

    for _ in range(2):
        _ok("find_pydantic_models", {"project_path": other.as_posix()}, server)

    assert len(_contexts_for(other)) == 1


def test_a_refusal_after_a_success_keeps_the_good_context(project: Path, tmp_path: Path) -> None:
    """Only the refused call's context is dropped, never one already serving calls."""
    other = tmp_path / "other"
    (other / "pkg").mkdir(parents=True)
    (other / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    server = _plugin_server(project)
    _ok("find_pydantic_models", {"project_path": other.as_posix()}, server)

    _assert_refused(
        "find_pydantic_models", {"scope": "package:/", "project_path": other.as_posix()}, server
    )

    assert len(_contexts_for(other)) == 1
