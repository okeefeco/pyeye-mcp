"""A base that isn't a class reference is unresolved, never a superclass (#922).

``class M(make_base())`` used to report the FUNCTION ``make_base`` as M's
superclass, with ``unresolved_superclasses: []``: confidently wrong (#505).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

_SOURCE = """
FLAG = True

class Real:
    pass

class Other:
    pass

def make_base():
    return Real

NotAClass = 3

class FromCall(make_base()):
    pass

class FromConditional(Real if FLAG else Other):
    pass

class FromFunction(make_base):
    pass

class FromVariable(NotAClass):
    pass

class FromSubscriptedCall(make_base()[0]):
    pass

class Normal(Real):
    pass
"""


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("non_class_bases")
    (root / "m.py").write_text(_SOURCE)
    return root


def _superclasses(project: Path, handle: str) -> Any:
    from pyeye.mcp.server import mcp

    result = asyncio.run(
        mcp.call_tool(
            "expand", {"handle": handle, "edge": "superclasses", "project_path": project.as_posix()}
        )
    )
    assert not result.is_error, result.content
    return result.structured_content


@pytest.mark.parametrize(
    ("handle", "text"),
    [
        ("m.FromCall", "make_base()"),
        ("m.FromConditional", "Real if FLAG else Other"),
        ("m.FromFunction", "make_base"),
        ("m.FromVariable", "NotAClass"),
        ("m.FromSubscriptedCall", "make_base()[0]"),
    ],
)
def test_a_non_class_base_is_unresolved(project: Path, handle: str, text: str) -> None:
    response = _superclasses(project, handle)

    assert response["stubs"] == [], response
    assert response["unresolved_superclasses"] == [text], response


def test_a_class_base_is_unchanged(project: Path) -> None:
    response = _superclasses(project, "m.Normal")

    assert [s["handle"] for s in response["stubs"]] == ["m.Real"]
    assert response["unresolved_superclasses"] == []
