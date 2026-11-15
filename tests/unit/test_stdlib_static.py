"""Static standard-library facts: public re-exports and platform decision points.

``pyeye._stdlib_static`` reads stdlib and typeshed sources with the AST. It
imports nothing, so a lookup can never run stdlib code, and every expectation
here is the same on every OS (#544, #329).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from pyeye._stdlib_static import (
    PlatformAnchor,
    is_stdlib,
    platform_decision_point,
    public_handle,
    stdlib_definition,
)


class TestIsStdlib:
    @pytest.mark.parametrize(
        "dotted", ["collections.abc.Mapping", "json", "os.path.join", "_collections_abc"]
    )
    def test_stdlib(self, dotted: str) -> None:
        assert is_stdlib(dotted)

    @pytest.mark.parametrize(
        "dotted", ["pyeye.resolver", "jedi.Script", "pytest", "notamodule.x", ""]
    )
    def test_not_stdlib(self, dotted: str) -> None:
        assert not is_stdlib(dotted)


class TestStdlibDefinition:
    @pytest.mark.parametrize("path", ["collections.abc.Mapping", "_collections_abc.Mapping"])
    def test_private_definition_gets_the_public_handle(self, path: str) -> None:
        found = stdlib_definition(path)

        assert found is not None
        assert found.handle == "collections.abc.Mapping"
        assert found.name == "Mapping"
        assert found.file.name == "_collections_abc.py"
        assert found.file.read_text().splitlines()[found.line - 1].startswith("class Mapping(")

    def test_member_follows_its_class(self) -> None:
        found = stdlib_definition("collections.abc.Mapping.get")

        assert found is not None
        assert found.handle == "collections.abc.Mapping.get"
        assert found.name == "get"
        assert found.file.name == "_collections_abc.py"
        assert found.file.read_text().splitlines()[found.line - 1].lstrip().startswith("def get(")

    @pytest.mark.parametrize(
        "path",
        [
            "json.JSONDecoder",  # defined in a PUBLIC module: the collapse rule applies
            "json.loads",
            "pathlib.Path",
            "collections.abc.NoSuchThing",
            "collections.abc",  # a module, not a class or function
            "pyeye.resolver.resolve_handle",  # not stdlib
            "os.sep",  # a constant
        ],
    )
    def test_outside_the_exception_is_none(self, path: str) -> None:
        assert stdlib_definition(path) is None


class TestPublicHandle:
    @pytest.mark.parametrize(
        ("full_name", "expected"),
        [
            ("_collections_abc.Mapping", "collections.abc.Mapping"),
            ("_collections_abc.Collection", "collections.abc.Collection"),
            ("_collections_abc.Mapping.get", "collections.abc.Mapping.get"),
            ("_collections_abc.Mapping.__slots__", "collections.abc.Mapping.__slots__"),
            # pathlib and random import it only to USE it; collections.abc re-exports
            ("_collections_abc.Sequence", "collections.abc.Sequence"),
            # an explicit import of a name in the public module's ``__all__``
            ("_weakrefset.WeakSet", "weakref.WeakSet"),
        ],
    )
    def test_private_is_renamed_to_its_public_reexporter(
        self, full_name: str, expected: str
    ) -> None:
        assert public_handle(full_name) == expected

    @pytest.mark.parametrize(
        "full_name",
        [
            "collections.abc.Mapping",  # already public
            "json.decoder.JSONDecoder",  # public definition module
            "typing.Mapping",
            "pyeye.resolver.Resolved",
            # threading imports it, but only weakref lists it in ``__all__``; a
            # private name never re-exported anywhere stays private:
            "_weakrefset._IterationGuard",
        ],
    )
    def test_unchanged(self, full_name: str) -> None:
        assert public_handle(full_name) is None


class TestPlatformDecisionPoint:
    @pytest.mark.parametrize("handle", ["os.path", "os.path.join", "os.path.exists"])
    def test_is_the_typeshed_platform_branch(self, handle: str) -> None:
        point = platform_decision_point(handle)

        assert point is not None
        assert point.file.as_posix().endswith("stdlib/os/path.pyi")
        lines = point.file.read_text().splitlines()
        assert lines[point.line_start - 1].startswith("if sys.platform")
        block = "\n".join(lines[point.line_start - 1 : point.line_end])
        assert "ntpath" in block and "posixpath" in block

    @pytest.mark.parametrize(
        "handle", ["os.sep", "posixpath.join", "ntpath.join", "json.loads", "os.pathsep"]
    )
    def test_outside_the_table_is_none(self, handle: str) -> None:
        assert platform_decision_point(handle) is None

    def test_anchor_reports_the_decision_point_and_delegates_the_rest(self) -> None:
        point = platform_decision_point("os.path.join")
        assert point is not None

        class _Name:
            type = "function"
            name = "join"
            full_name = "os.path.join"
            module_path = "/somewhere/ntpath.py"
            line = 108
            column = 4

            def get_signatures(self) -> list[str]:
                return ["join(a, *p)"]

        anchor = PlatformAnchor(_Name(), point)

        assert (anchor.module_path, anchor.line, anchor.end_line) == (
            point.file,
            point.line_start,
            point.line_end,
        )
        assert (anchor.type, anchor.full_name, anchor.get_signatures()) == (
            "function",
            "os.path.join",
            ["join(a, *p)"],
        )


def test_lookups_import_nothing() -> None:
    """Static means static: no stdlib module is imported to answer a lookup."""
    script = textwrap.dedent("""
        import sys
        from pyeye._stdlib_static import platform_decision_point, public_handle, stdlib_definition
        before = set(sys.modules)
        stdlib_definition("collections.abc.Mapping.get")
        public_handle("_collections_abc.Mapping")
        platform_decision_point("os.path.join")
        stdlib_definition("antigravity.geohash")
        print(sorted(set(sys.modules) - before))
        """)
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    ).stdout.strip()

    assert out == "[]"
