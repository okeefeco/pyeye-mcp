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
