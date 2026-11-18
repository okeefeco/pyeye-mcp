"""``resolve`` accepts ``.pyi`` stub paths (#885).

- A stub beside its ``.py`` source resolves exactly as the source does, in
  every file form: the same handle, kind, scope and location (the ``.py``).
- A stub with no source beside it stays not-found, saying why. A handle for
  it would be one no other tool accepts (#602), and no hint names a ``.py``
  that isn't there.
- An external stub (typeshed, a ``-stubs`` package) behaves like any external
  file path: it doesn't resolve by path. Pinned here so a change is deliberate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye.mcp.operations.resolve import _parse_identifier
from pyeye.mcp.server import mcp

_STUB_ONLY = "stub with no .py source beside it"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text("def f(x):\n    return x\n\nclass C:\n    pass\n", encoding="utf-8")
    (pkg / "mod.pyi").write_text("def f(x: int) -> int: ...\n\nclass C: ...\n", encoding="utf-8")
    (pkg / "stubonly.pyi").write_text("def g() -> str: ...\n\nclass S: ...\n", encoding="utf-8")
    return tmp_path


async def _call(tool: str, project: Path, **args: Any) -> dict[str, Any]:
    result = await mcp.call_tool(tool, {**args, "project_path": project.as_posix()})
    assert not result.is_error, result.content
    response: dict[str, Any] = result.structured_content  # type: ignore[assignment]
    return response


def _answer(response: dict[str, Any]) -> tuple[Any, ...]:
    location = response.get("location") or {}
    return (
        response.get("found"),
        response.get("handle"),
        response.get("kind"),
        response.get("scope"),
        location.get("file"),
        location.get("line_start"),
    )


class TestStubBesideItsSource:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("spelling", ["pkg/mod.pyi", "{root}/pkg/mod.pyi"])
    async def test_the_file_resolves_as_its_source(self, project: Path, spelling: str) -> None:
        stub = await _call("resolve", project, identifier=spelling.format(root=project.as_posix()))
        source = await _call("resolve", project, identifier="pkg/mod.py")

        assert stub["found"] is True and stub["handle"] == "pkg.mod" and stub["kind"] == "module"
        assert _answer(stub) == _answer(source)
        assert stub["location"]["file"].endswith("pkg/mod.py")

    @pytest.mark.asyncio
    async def test_file_line_and_resolve_at_still_land_on_the_source(self, project: Path) -> None:
        by_line = await _call("resolve", project, identifier="pkg/mod.pyi:3")
        at = await _call("resolve_at", project, file="pkg/mod.pyi", line=3, column=6)
        source = await _call("resolve", project, identifier="pkg/mod.py:4")

        assert by_line["handle"] == at["handle"] == "pkg.mod.C"
        assert _answer(by_line) == _answer(at) == _answer(source)

    @pytest.mark.asyncio
    async def test_the_handle_round_trips(self, project: Path) -> None:
        stub = await _call("resolve", project, identifier="pkg/mod.pyi")
        inspected = await _call("inspect", project, handle=stub["handle"])

        assert inspected["found"] is True and inspected["handle"] == "pkg.mod"


class TestStubOnly:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tool", "args"),
        [
            ("resolve", {"identifier": "pkg/stubonly.pyi"}),
            ("resolve", {"identifier": "pkg/stubonly.pyi:3"}),
            ("resolve_at", {"file": "pkg/stubonly.pyi", "line": 3, "column": 6}),
        ],
    )
    async def test_every_file_form_is_an_honest_miss(
        self, project: Path, tool: str, args: dict[str, Any]
    ) -> None:
        miss = await _call(tool, project, **args)

        assert miss["found"] is False and miss["reason"] == "unresolved"
        assert _STUB_ONLY in miss["detail"]
        assert "stubonly.py'" not in miss["detail"]  # no call to a file that doesn't exist

    @pytest.mark.asyncio
    async def test_it_has_no_handle_anywhere(self, project: Path) -> None:
        """Consistent with every other tool: the stub-only module isn't analysed."""
        assert (await _call("resolve", project, identifier="pkg.stubonly"))["found"] is False
        assert (await _call("inspect", project, handle="pkg.stubonly"))["found"] is False
        submodules = await _call("expand", project, handle="pkg", edge="submodules")
        assert [s["handle"] for s in submodules["stubs"]] == ["pkg.mod"]

    @pytest.mark.asyncio
    async def test_a_line_that_names_an_import_still_resolves(self, project: Path) -> None:
        """Only a miss gets the stub-only detail: a stub line that points elsewhere resolves."""
        (project / "pkg" / "stubonly.pyi").write_text(
            "import os\n\ndef g() -> str: ...\n", encoding="utf-8"
        )
        found = await _call("resolve_at", project, file="pkg/stubonly.pyi", line=1, column=7)

        assert found["found"] is True and found["handle"] == "os" and found["scope"] == "external"

    @pytest.mark.asyncio
    async def test_a_missing_stub_is_file_not_found(self, project: Path) -> None:
        miss = await _call("resolve", project, identifier="pkg/nope.pyi")

        assert miss["reason"] == "file_not_found"


class TestIdentifierForms:
    @pytest.mark.parametrize(
        ("identifier", "kind"),
        [
            ("mod.pyi", "file_only"),
            ("mod.pyi:3", "file_with_line"),
            ("mod.py", "file_only"),
            ("pkg.mod.pyx", "dotted_name"),
            ("pkg.mod.pyi_thing", "dotted_name"),
        ],
    )
    def test_a_pyi_suffix_is_a_file(self, identifier: str, kind: str) -> None:
        assert _parse_identifier(identifier)["kind"] == kind


class TestExternalStubs:
    @staticmethod
    def _typeshed_stub() -> Path:
        import jedi

        stub = Path(jedi.__file__).parent / "third_party" / "typeshed" / "stdlib" / "abc.pyi"
        if not stub.is_file():
            pytest.skip("this Jedi has no bundled typeshed")
        return stub

    @pytest.mark.asyncio
    async def test_a_typeshed_stub_is_a_stub_only_miss(self, project: Path) -> None:
        stub = self._typeshed_stub()
        miss = await _call("resolve", project, identifier=stub.as_posix())

        assert miss["found"] is False and miss["reason"] == "unresolved"
        assert _STUB_ONLY in miss["detail"]

    @pytest.mark.asyncio
    async def test_a_stubs_package_is_a_stub_only_miss(self, project: Path, tmp_path: Path) -> None:
        """A ``foo-stubs`` package beside its real package: the stub has no .py beside it."""
        site = tmp_path / "site"
        (site / "foo-stubs").mkdir(parents=True)
        (site / "foo").mkdir()
        (site / "foo-stubs" / "__init__.pyi").write_text("X: int\n", encoding="utf-8")
        (site / "foo" / "__init__.py").write_text("X = 1\n", encoding="utf-8")

        miss = await _call(
            "resolve", project, identifier=(site / "foo-stubs" / "__init__.pyi").as_posix()
        )

        assert miss["found"] is False and miss["reason"] == "unresolved"
        assert _STUB_ONLY in miss["detail"]
