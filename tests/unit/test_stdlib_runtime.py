"""The running interpreter is the authority on standard-library facts (#544).

``pyeye._stdlib_runtime.runtime_definition`` names a stdlib symbol the way the
runtime does (``__module__`` + ``__qualname__``) and locates it at the runtime
definition's source. It introspects the standard library only: project and
site-packages code is never imported.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

from pyeye._stdlib_runtime import is_stdlib, runtime_definition, stdlib_canonical


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


class TestRuntimeDefinition:
    def test_collections_abc_class_is_named_by_the_runtime(self) -> None:
        found = runtime_definition("collections.abc.Mapping")

        # ``inspect.getsourcefile`` follows ``__module__`` to collections/abc.py,
        # which does not define the class; the runtime file is _collections_abc.py.
        assert found is not None
        assert found.handle == "collections.abc.Mapping"
        assert found.name == "Mapping"
        assert found.file.name == "_collections_abc.py"
        assert found.file.read_text().splitlines()[found.line - 1].startswith("class Mapping(")

    def test_private_alias_names_the_same_object(self) -> None:
        assert runtime_definition("_collections_abc.Mapping") == runtime_definition(
            "collections.abc.Mapping"
        )

    def test_method_takes_its_owner_class_module(self) -> None:
        # ``Mapping.get.__module__`` is ``_collections_abc``; only the class was
        # renamed, so the member's handle follows its owner.
        found = runtime_definition("collections.abc.Mapping.get")

        assert found is not None
        assert found.handle == "collections.abc.Mapping.get"
        assert found.name == "get"
        assert found.file.name == "_collections_abc.py"

    def test_reexport_resolves_to_the_definition_module(self) -> None:
        found = runtime_definition("json.JSONDecoder")

        assert found is not None
        assert found.handle == f"{json.JSONDecoder.__module__}.JSONDecoder"
        assert found.file.name == "decoder.py"

    def test_matches_pathlib_runtime_layout(self) -> None:
        found = runtime_definition("pathlib.Path")

        assert found is not None
        assert found.handle == f"{pathlib.Path.__module__}.Path"

    @pytest.mark.parametrize(
        "dotted",
        [
            "json",  # a module, not a class or function
            "json.decoder.JSONDecodeError.nope",  # missing attribute
            "collections.abc.NoSuchThing",
            "pyeye.resolver.resolve_handle",  # not stdlib: never imported
            "typing.Mapping",  # an alias instance, not a definition
            "os.sep",  # a constant
        ],
    )
    def test_no_definition(self, dotted: str) -> None:
        assert runtime_definition(dotted) is None

    def test_c_implemented_object_without_source_is_none(self) -> None:
        # ``len`` is a C builtin: the runtime knows it, but there is no source.
        assert runtime_definition("builtins.len") is None

    def test_never_imports_a_side_effect_module(self) -> None:
        sys.modules.pop("antigravity", None)
        assert runtime_definition("antigravity.geohash") is None
        assert "antigravity" not in sys.modules

    def test_never_imports_project_or_site_packages(self) -> None:
        sys.modules.pop("pyeye_never_imported_xyz", None)
        assert runtime_definition("pyeye_never_imported_xyz.thing") is None
        assert "pyeye_never_imported_xyz" not in sys.modules


class TestStdlibCanonical:
    """``stdlib_canonical`` rewrites a Jedi ``full_name`` to the runtime's handle."""

    @pytest.mark.parametrize(
        ("full_name", "expected"),
        [
            ("_collections_abc.Mapping", "collections.abc.Mapping"),
            ("_collections_abc.Collection", "collections.abc.Collection"),
            ("_collections_abc.Mapping.get", "collections.abc.Mapping.get"),
            # a member that is not a class/function follows its runtime owner
            ("_collections_abc.Mapping.__slots__", "collections.abc.Mapping.__slots__"),
        ],
    )
    def test_rewrites(self, full_name: str, expected: str) -> None:
        assert stdlib_canonical(full_name) == expected

    @pytest.mark.parametrize(
        "full_name",
        [
            "collections.abc.Mapping",
            "json.loads",
            "json.decoder.JSONDecoder",
            "os.sep",
            "typing.Mapping",
            "pyeye.resolver.Resolved",
            "json",
        ],
    )
    def test_already_canonical_or_not_applicable_is_unchanged(self, full_name: str) -> None:
        assert stdlib_canonical(full_name) is None
