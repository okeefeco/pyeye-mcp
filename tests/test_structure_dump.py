"""The structure dump: what pyeye knows about every module, collected statically (#1092)."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from pyeye.docs_facts.structure import dump
from tests.utils.structure import write_project


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_project(tmp_path_factory.mktemp("structure"))


@pytest.fixture(scope="module")
def collected(project: Path) -> dump.Dump:
    return dump.collect(project)


class TestHelpers:
    def test_first_line_skips_blank_lines_and_cuts(self) -> None:
        assert dump.first_line("\n\n  Hello.  \nMore") == "Hello."
        assert dump.first_line(None) == ""
        assert len(dump.first_line("x" * 500)) == dump.SUMMARY_CHARS

    @pytest.mark.parametrize(
        ("rel", "include", "exclude", "expected"),
        [
            ("pkg/a.py", ("*",), (), True),
            ("pkg/a.py", ("src/*",), (), False),
            ("pkg/tests/t.py", ("*",), ("*/tests/*",), False),
            ("pkg/deep/er/a.py", ("pkg/*",), (), True),  # * crosses /
        ],
    )
    def test_selected(
        self, rel: str, include: tuple[str, ...], exclude: tuple[str, ...], expected: bool
    ) -> None:
        assert dump.selected(rel, include, exclude) is expected

    def test_walk_definitions_matches_members_scoping(self) -> None:
        source = (
            "import sys\n"
            "if sys.version_info >= (3, 11):\n    def cond(): ...\nelse:\n    def cond(): ...\n"
            "try:\n    def in_try(): ...\nexcept Exception:\n    def in_except(): ...\n"
            "finally:\n    def in_finally(): ...\n"
            "with open(__file__):\n    def in_with(): ...\n"
            "while False:\n    def in_while(): ...\n"
            "match sys.argv:\n    case _:\n        def in_case(): ...\n"
            "def outer():\n    def inner(): ...\n"
            "class K:\n    if True:\n        def kif(self): ...\n"
            "    class Nested:\n        async def nm(self): ...\n"
        )
        paths = [p for p, _ in dump.walk_definitions(ast.parse(source).body)]

        assert paths == [
            "cond",
            "cond",
            "in_try",
            "in_except",
            "in_finally",
            "in_with",
            "in_while",
            "in_case",
            "outer",
            "K",
            "K.kif",
            "K.Nested",
            "K.Nested.nm",
        ]

    def test_docstrings_prefers_the_first_non_empty_one(self) -> None:
        """An @overload stub has no docstring; its implementation's is the one shown."""
        source = (
            '"""Mod doc.\n\nMore."""\n'
            "from typing import overload\n"
            "@overload\ndef f(x: int) -> int: ...\n"
            '@overload\ndef f(x: str) -> str: ...\ndef f(x):\n    """Impl doc."""\n'
            'class C:\n    def m(self):\n        """M doc."""\n'
        )
        summary, docs = dump.docstrings(source)

        assert summary == "Mod doc."
        assert docs == {"f": "Impl doc.", "C": "", "C.m": "M doc."}


class TestCollect:
    def test_modules_cover_every_mapped_file(self, collected: dump.Dump) -> None:
        assert [m.handle for m in collected.modules] == [
            "pkg",
            "pkg.cfg",
            "pkg.hooks",
            "pkg.old",
            "pkg.paths",
            "pkg.settings",
            "pkg.shapes",
            "pkg.star",
            "pkg.util",
        ]
        assert collected.unmapped == ("bad-dir/x.py",)
        assert collected.unresolved == ()
        assert collected.refused == ()

    def test_definitions_carry_signature_summary_and_owner(self, collected: dump.Dump) -> None:
        helper = collected.by_handle["pkg.paths.helper"]
        assert helper == dump.Definition(
            handle="pkg.paths.helper",
            kind="function",
            module="pkg.paths",
            owner="pkg.paths",
            signature="helper(path: str, strict: bool=False) -> str",
            summary="Normalise a file path.",
        )
        area = collected.by_handle["pkg.shapes.Square.area"]
        assert (area.kind, area.owner, area.module) == ("method", "pkg.shapes.Square", "pkg.shapes")
        assert collected.by_handle["pkg.shapes.Base"].summary == "A shape."

    def test_module_facts(self, collected: dump.Dump) -> None:
        modules = {m.handle: m for m in collected.modules}
        paths, util, shapes, cfg = (
            modules[n] for n in ("pkg.paths", "pkg.util", "pkg.shapes", "pkg.cfg")
        )

        assert (paths.file, paths.summary) == ("pkg/paths.py", "Path helpers.")
        assert (paths.imported_by, paths.importers) == (1, ("pkg.util",))
        assert "pkg.paths.helper" in util.imports
        assert shapes.type_only_imports == ("pkg.util",)
        assert "pkg.util" not in shapes.imports
        assert cfg.unresolved_imports == ("missing_dependency",)
        assert all(m.measured_imports for m in collected.modules)

    def test_unreadable_definitions_are_kept(self, collected: dump.Dump) -> None:
        """A def pyeye can't read is listed with its reason, never dropped (#1074)."""
        assert collected.unreadable == (
            dump.Unreadable(
                handle="pkg.star.star",
                kind="function",
                line=1,
                reason="parser_unsupported_syntax",
            ),
        )
        assert "pkg.star.after_star" in collected.by_handle

    def test_include_and_exclude(self, project: Path) -> None:
        only = dump.collect(project, include=("pkg/*",), exclude=("*/hooks.py", "*/star.py"))

        names = {m.handle for m in only.modules}
        assert "pkg.hooks" not in names and "pkg.star" not in names
        assert "pkg.paths" in names
        assert only.unmapped == ()

    def test_imported_by_honours_total(self, project: Path) -> None:
        """When pyeye caps the list, ``total`` is the count (#435)."""

        class Capped(dump.Pyeye):
            def expand(self, handle: str, edge: str) -> dict[str, Any]:
                result = super().expand(handle, edge)
                if edge == "imported_by" and handle == "pkg.paths":
                    return {**result, "total": 40}
                return result

        with Capped(project) as ops:
            capped = dump.collect(project, include=("pkg/paths.py",), pyeye=ops)

        assert capped.modules[0].imported_by == 40

    def test_unresolved_and_unmeasured_modules_are_reported(self, project: Path) -> None:
        class Blind(dump.Pyeye):
            def expand(self, handle: str, edge: str) -> dict[str, Any]:
                if handle == "pkg.settings" and edge == "members":
                    return {"found": True, "unsupported": True, "reason": "unparseable"}
                if handle == "pkg.paths" and edge in ("imports", "imported_by"):
                    return {"found": False}
                return super().expand(handle, edge)

        with Blind(project) as ops:
            blind = dump.collect(project, include=("pkg/paths.py", "pkg/settings.py"), pyeye=ops)

        assert blind.unresolved == (("pkg.settings", "unparseable"),)
        (paths,) = blind.modules
        assert (paths.imported_by, paths.measured_imports, paths.imports) == (None, False, ())

    def test_a_file_the_ast_cant_read_still_dumps_without_summaries(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken(_source: str) -> Any:
            raise SyntaxError("nope")

        monkeypatch.setattr(dump, "docstrings", broken)

        got = dump.collect(project, include=("pkg/paths.py",))

        assert got.by_handle["pkg.paths.helper"].summary == ""
        assert got.modules[0].summary == ""


def test_relative_keeps_a_path_outside_the_root_as_given(tmp_path: Path) -> None:
    assert dump.relative(tmp_path / "a" / "b.py", tmp_path) == "a/b.py"
    assert dump.relative(Path("/elsewhere/c.py"), tmp_path) == "/elsewhere/c.py"


class TestPyeye:
    def test_close_stops_the_watchers_and_is_idempotent(self, project: Path) -> None:
        ops = dump.Pyeye(project)
        ops.close()  # never started: nothing to stop
        assert ops.analyzer is not None
        manager = ops._manager
        assert manager is not None and manager.watchers

        ops.close()
        ops.close()

        assert not manager.watchers and ops._manager is None


class TestSourceOnly:
    def test_compiled_modules_are_refused_and_restored(self) -> None:
        from jedi.inference import imports

        original = imports._load_builtin_module
        with dump.source_only() as refused:
            assert imports._load_builtin_module is not original
            assert imports._load_builtin_module(None, ("_some_compiled",), None) is None
        assert imports._load_builtin_module is original
        assert refused == ["_some_compiled"]

    def test_builtins_still_load(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from jedi.inference import imports

        calls: list[tuple[str, ...]] = []

        def load(_state: object, names: tuple[str, ...], _sys_path: object) -> str:
            calls.append(names)
            return "mod"

        monkeypatch.setattr(imports, "_load_builtin_module", load)

        with dump.source_only() as refused:
            assert imports._load_builtin_module(None, ("builtins",), None) == "mod"
        assert calls == [("builtins",)] and refused == []

    def test_a_missing_seam_refuses_to_collect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Running on would load compiled modules, so it stops instead."""
        from jedi.inference import imports

        monkeypatch.delattr(imports, "_load_builtin_module")

        with (
            pytest.raises(RuntimeError, match="compiled modules can't be refused"),
            dump.source_only(),
        ):
            pass

    def test_strict_collect_reports_what_it_refused(self, tmp_path: Path) -> None:
        """``sys`` is compiled into every interpreter, so a strict run refuses it."""
        (tmp_path / "mod.py").write_text("import sys\n\n\ndef f(): ...\n", encoding="utf-8")

        strict = dump.collect(tmp_path, strict_source=True)

        assert "sys" in strict.refused
        assert strict.refused == tuple(sorted(set(strict.refused)))
        assert [d.handle for d in strict.definitions] == ["mod.f"]
