"""A decision's ``Applies-to`` sites, resolved through pyeye (#1178; shared with #1182).

The user ruled (2026-11-23): sites resolve through pyeye's resolver to canonical
handles, so a re-exported path names its definition site, and an unresolved
site is reported, never silently unmatched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye import decision_sites
from pyeye.decision_sites import Ref, Site, pyeye_resolver, refs, resolve_sites


def site_texts(text: str | None) -> list[str]:
    return [r.text for r in refs(text)]


class TestSiteTexts:
    def test_backticked_code_references_are_sites(self) -> None:
        text = (
            "- `pkg.mod.func` and `pkg.mod.Cls.method`; the tests in "
            "`tests/test_mod.py` (`TestX`)"
        )

        assert site_texts(text) == ["pkg.mod.func", "pkg.mod.Cls.method", "tests/test_mod.py"]

    def test_a_none_value_and_a_missing_value_have_no_sites(self) -> None:
        assert site_texts("none (policy decision: release classification)") == []
        assert site_texts(None) == []

    def test_config_files_and_prose_in_backticks_are_not_sites(self) -> None:
        text = (
            "`pyproject.toml`, `uv.lock`, `.github/dependabot.yml`, `watchdog>=7.1.1,<8`, `x = 1`"
        )

        assert site_texts(text) == []

    def test_a_single_word_is_not_a_site(self) -> None:
        """A bare name would resolve by guesswork (any same-named definition)."""
        assert site_texts("`on_attrib` beside `on_modified`") == []

    def test_call_parentheses_and_pytest_node_ids_are_trimmed(self) -> None:
        text = "`pkg.mod.func()`, `tests/test_mod.py::TestX::test_y`"

        assert site_texts(text) == ["pkg.mod.func", "tests/test_mod.py"]

    def test_each_site_once_in_first_order(self) -> None:
        assert site_texts("`a.b`, `c.d`, `a.b`") == ["a.b", "c.d"]

    def test_each_reference_has_its_kind_and_line(self) -> None:
        text = "first `pkg.mod.func`\nthen `tests/test_mod.py::T` and `pkg.mod.func` again"

        assert refs(text, first_line=40) == [
            Ref("pkg.mod.func", "handle", 40),
            Ref("tests/test_mod.py", "path", 41),
        ]

    def test_prose_and_bare_shorthands_are_not_references(self) -> None:
        """A bare `_read_source` after a qualified name, or "every X in REGISTRY", is prose."""
        text = "`pkg.base.Plugin._read_text`, then `_read_source`; every edge in `EDGE_RESOLVERS`"

        assert site_texts(text) == ["pkg.base.Plugin._read_text"]


class _Fake:
    def __init__(self, answers: dict[str, tuple[str | None, str | None]]) -> None:
        self.answers = answers

    def canonical(self, identifier: str) -> tuple[str | None, str | None]:
        return self.answers.get(identifier, (None, "unresolved"))


class TestResolveSites:
    def test_each_site_carries_its_handle_or_why_not(self) -> None:
        fake = _Fake({"pkg.Thing": ("pkg.impl.Thing", None)})

        assert resolve_sites("`pkg.Thing` and `pkg.gone`", fake) == [
            Site(Ref("pkg.Thing", "handle", 1), "pkg.impl.Thing", None),
            Site(Ref("pkg.gone", "handle", 1), None, "unresolved"),
        ]

    def test_no_sites_means_no_questions(self) -> None:
        class Refuse:
            def canonical(self, _identifier: str) -> tuple[str | None, str | None]:
                raise AssertionError("no site, no resolve")

        assert resolve_sites("none (policy)", Refuse()) == []


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("decision_sites")
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from pkg.impl import Thing\n", encoding="utf-8")
    (pkg / "impl.py").write_text(
        "class Thing:\n    def go(self) -> None:\n        pass\n", encoding="utf-8"
    )
    return root


class TestPyeyeResolver:
    def test_a_re_exported_path_resolves_to_its_definition_site(self, project: Path) -> None:
        assert pyeye_resolver(project).canonical("pkg.Thing") == ("pkg.impl.Thing", None)

    def test_a_method_resolves(self, project: Path) -> None:
        assert pyeye_resolver(project).canonical("pkg.impl.Thing.go") == ("pkg.impl.Thing.go", None)

    def test_a_file_path_resolves_to_its_module(self, project: Path) -> None:
        assert pyeye_resolver(project).canonical("pkg/impl.py") == ("pkg.impl", None)

    def test_an_unknown_name_is_unresolved_with_a_reason(self, project: Path) -> None:
        handle, reason = pyeye_resolver(project).canonical("pkg.impl.Nope")

        assert handle is None
        assert reason == "unresolved"

    def test_an_external_name_is_not_a_project_site(self, project: Path) -> None:
        handle, reason = pyeye_resolver(project).canonical("os.path.join")

        assert handle is None
        assert reason == "external"

    def test_the_analyzer_is_built_on_the_first_question(self, project: Path) -> None:
        resolver = pyeye_resolver(project)

        assert resolver._analyzer is None  # type: ignore[attr-defined]
        resolver.canonical("pkg.impl")
        assert resolver._analyzer is not None  # type: ignore[attr-defined]


def test_the_module_imports_no_analysed_code() -> None:
    """C19: resolving is static; nothing of the analysed project is imported or run."""
    assert "importlib" not in Path(decision_sites.__file__).read_text(encoding="utf-8")


class TestShortForms:
    """A dotted name is a handle, an external, or a short form, read from the layout (#1182, #1178).

    ``JediAnalyzer.find_importers`` or ``outline._is_package`` name something,
    but only a guess turns them into a handle. Whether a name is rooted is
    read from the project's layout, never by resolving: a project top-level
    package or module makes a ``handle``; a standard-library or environment
    one an ``external``; anything else is a ``short_form``.
    """

    _TOPS = frozenset({"pkg"})
    _EXTERNAL = frozenset({"os", "jedi", "inspect"})

    def _refs(self, text: str, first_line: int = 1) -> list[Ref]:
        return refs(text, first_line, tops=self._TOPS, external=self._EXTERNAL)

    def test_a_name_rooted_at_a_project_top_is_a_handle(self) -> None:
        assert self._refs("`pkg.impl.Thing`") == [Ref("pkg.impl.Thing", "handle", 1)]

    def test_a_name_rooted_at_a_stdlib_or_environment_top_is_external(self) -> None:
        assert [r.kind for r in self._refs("`os.path.join` and `jedi.Project`")] == [
            "external",
            "external",
        ]

    def test_an_unrooted_dotted_name_is_a_short_form(self) -> None:
        found = self._refs("`JediAnalyzer.find_importers` and `outline._is_package`", 3)

        assert found == [
            Ref("JediAnalyzer.find_importers", "short_form", 3),
            Ref("outline._is_package", "short_form", 3),
        ]

    def test_a_project_top_wins_over_a_stdlib_name(self) -> None:
        """A project package named like a stdlib module is the project's."""
        found = refs("`inspect.thing`", tops={"inspect"}, external={"inspect"})

        assert found == [Ref("inspect.thing", "handle", 1)]

    def test_paths_are_unaffected(self) -> None:
        assert self._refs("`tests/test_mod.py`") == [Ref("tests/test_mod.py", "path", 1)]

    def test_without_tops_nothing_is_a_short_form(self) -> None:
        """Callers that don't pass the layout keep the original classification."""
        assert refs("`JediAnalyzer.find_importers`") == [
            Ref("JediAnalyzer.find_importers", "handle", 1)
        ]

    def test_a_short_form_is_never_resolved(self) -> None:
        class Refuse:
            def canonical(self, _identifier: str) -> tuple[str | None, str | None]:
                raise AssertionError("a short form is never resolved")

        sites = resolve_sites(
            "`outline._is_package`", Refuse(), tops=self._TOPS, external=self._EXTERNAL
        )

        assert sites == [Site(Ref("outline._is_package", "short_form", 1), None, "short_form")]

    def test_an_external_is_resolved_and_keeps_its_answer(self) -> None:
        fake = _Fake({"os.path.join": (None, "external")})

        sites = resolve_sites(
            "`os.path.join` and `inspect.inspect`", fake, tops=self._TOPS, external=self._EXTERNAL
        )

        assert [(s.ref.kind, s.reason) for s in sites] == [
            ("external", "external"),
            ("external", "unresolved"),
        ]


class TestTopLevelNames:
    def test_the_projects_packages_and_modules(self, tmp_path: Path) -> None:
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "tool.py").write_text("X = 1\n", encoding="utf-8")

        assert {"pkg", "tool"} <= decision_sites.top_level_names(tmp_path)

    def test_a_src_layout_package(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "mylib").mkdir(parents=True)
        (tmp_path / "src" / "mylib" / "__init__.py").write_text("", encoding="utf-8")

        assert "mylib" in decision_sites.top_level_names(tmp_path)

    def test_the_standard_library_is_external(self, tmp_path: Path) -> None:
        external = decision_sites.external_top_level_names(tmp_path)

        assert {"os", "ast", "pathlib"} <= external
        assert "os" not in decision_sites.top_level_names(tmp_path)

    def test_the_projects_environment_is_external(self, tmp_path: Path) -> None:
        site = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
        (site / "somelib").mkdir(parents=True)
        (tmp_path / ".venv" / "pyvenv.cfg").write_text("version = 3.12.0\n", encoding="utf-8")

        assert "somelib" in decision_sites.external_top_level_names(tmp_path)
        assert "somelib" not in decision_sites.top_level_names(tmp_path)

    def test_a_short_name_is_neither(self, project: Path) -> None:
        assert "JediAnalyzer" not in decision_sites.top_level_names(project)
        assert "JediAnalyzer" not in decision_sites.external_top_level_names(project)
