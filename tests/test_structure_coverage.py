"""Coverage: the definitions on disk against the dump; a gap is never silent (#1092)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from pyeye.docs_facts.structure import coverage, dump
from tests.utils.structure import write_project


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_project(tmp_path_factory.mktemp("structure"))


@pytest.fixture(scope="module")
def collected(project: Path) -> dump.Dump:
    return dump.collect(project)


def _module(handle: str, file: str) -> dump.Module:
    return dump.Module(handle, file, "", 0, (), (), (), (), True)


def _definition(handle: str, kind: str = "function") -> dump.Definition:
    module, _ = handle.rsplit(".", 1)
    return dump.Definition(handle, kind, module, module, None, "")


def test_defined_lists_functions_classes_and_methods() -> None:
    source = (
        "def f(): ...\n"
        "class C:\n    def m(self): ...\n    class N:\n        def n(self): ...\n"
        "def outer():\n    def inner(): ...\n"
    )

    assert coverage.defined(source, "pkg.mod") == {
        "pkg.mod.f",
        "pkg.mod.C",
        "pkg.mod.C.m",
        "pkg.mod.C.N",
        "pkg.mod.C.N.n",
        "pkg.mod.outer",
    }


def test_the_fixture_has_no_gaps_but_reports_its_unreadable_def(
    collected: dump.Dump, project: Path
) -> None:
    """The PEP 646 def is unreadable: listed, not a gap (#1074). The bad dir is unmapped."""
    found = coverage.compare(collected, project)

    assert found.missing == () and found.phantom == () and found.unparseable == ()
    assert found.unreadable == ("pkg.star.star",)
    assert found.unmapped == ("bad-dir/x.py",)
    assert found.dumped == found.on_disk - 1
    assert found.gaps  # the unmapped file is unaccounted for


def test_without_the_unmapped_file_it_is_clean(project: Path) -> None:
    clean = dump.collect(project, include=("pkg/*",))

    found = coverage.compare(clean, project)

    assert not found.gaps
    assert found.unreadable == ("pkg.star.star",)


def test_a_definition_the_dump_lost_is_missing(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("def kept(): ...\ndef lost(): ...\n", encoding="utf-8")
    partial = dump.Dump(modules=(_module("mod", "mod.py"),), definitions=(_definition("mod.kept"),))

    found = coverage.compare(partial, tmp_path)

    assert found.missing == ("mod.lost",)
    assert (found.on_disk, found.dumped) == (2, 1)
    assert found.gaps


def test_a_dumped_name_not_on_disk_is_phantom(tmp_path: Path) -> None:
    """#1074's failure: a parser that drops a def leaks its body's names as members."""
    (tmp_path / "mod.py").write_text("def real(): ...\n", encoding="utf-8")
    leaky = dump.Dump(
        modules=(_module("mod", "mod.py"),),
        definitions=(_definition("mod.real"), _definition("mod.leaked")),
    )

    found = coverage.compare(leaky, tmp_path)

    assert found.phantom == ("mod.leaked",)
    assert found.gaps


def test_an_unparseable_file_and_an_unresolved_module_are_gaps(
    collected: dump.Dump, tmp_path: Path
) -> None:
    (tmp_path / "broken.py").write_text("def (:\n", encoding="utf-8")
    broken = dataclasses.replace(
        collected,
        modules=(_module("broken", "broken.py"),),
        definitions=(),
        unreadable=(),
        unmapped=(),
        unresolved=(("ghost", "not found"),),
    )

    found = coverage.compare(broken, tmp_path)

    assert found.unparseable == ("broken.py",)
    assert found.unresolved == ("ghost (not found)",)
    assert found.gaps


class TestSkipped:
    """Files the project scan leaves out of a dumped package are gaps, not silence."""

    @staticmethod
    def _tree(root: Path) -> None:
        for rel in (
            "pkg/__init__.py",
            "pkg/a.py",
            "pkg/lost.py",
            "pkg/sub/__init__.py",
            "pkg/sub/deep.py",
            "pkg/ns/loose.py",  # a namespace directory: not looked into
            "pkg/data.txt",
        ):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("", encoding="utf-8")

    def test_a_file_and_a_sub_package_the_dump_lacks(self, tmp_path: Path) -> None:
        self._tree(tmp_path)
        partial = dump.Dump(
            modules=(_module("pkg", "pkg/__init__.py"), _module("pkg.a", "pkg/a.py")),
            definitions=(),
        )

        found = coverage.compare(partial, tmp_path)

        assert found.skipped == ("pkg/lost.py", "pkg/sub/__init__.py")
        assert found.gaps

    def test_files_the_caller_excluded_are_not_skipped(self, tmp_path: Path) -> None:
        self._tree(tmp_path)
        partial = dump.Dump(
            modules=(_module("pkg", "pkg/__init__.py"), _module("pkg.a", "pkg/a.py")),
            definitions=(),
        )

        found = coverage.compare(partial, tmp_path, exclude=("pkg/lost.py", "pkg/sub/*"))

        assert found.skipped == ()

    def test_a_dumped_sub_package_is_looked_into(self, tmp_path: Path) -> None:
        self._tree(tmp_path)
        whole = dump.Dump(
            modules=(
                _module("pkg", "pkg/__init__.py"),
                _module("pkg.a", "pkg/a.py"),
                _module("pkg.lost", "pkg/lost.py"),
                _module("pkg.sub", "pkg/sub/__init__.py"),
            ),
            definitions=(),
        )

        assert coverage.compare(whole, tmp_path).skipped == ("pkg/sub/deep.py",)

    def test_a_stub_init_counts_as_a_package(self, tmp_path: Path) -> None:
        (tmp_path / "pkg" / "typed").mkdir(parents=True)
        (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "pkg" / "typed" / "__init__.pyi").write_text("", encoding="utf-8")
        only = dump.Dump(modules=(_module("pkg", "pkg/__init__.py"),), definitions=())

        assert coverage.compare(only, tmp_path).skipped == ("pkg/typed/__init__.pyi",)
