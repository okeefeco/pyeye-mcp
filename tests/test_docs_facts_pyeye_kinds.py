"""pyeye's extractors as ``pyeye-*`` built-in kinds, restricted to its repository (#1107).

The maintainer's ruling (via designer, 2026-11-23): each pyeye extractor is a
built-in kind ``pyeye-*`` that pyeye's config lists; the kinds run only on
pyeye's own repository, with an error naming the restriction anywhere else; and
each kind's docstring states why no generic kind can express it. #1119 tracks
converting them, from a baseline of :data:`BASELINE` kinds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.docs_facts import kinds, pyeye_kinds, registry
from pyeye.docs_facts.cli import main
from pyeye.docs_facts.facts import ExtractionError

ROOT = Path(__file__).resolve().parent.parent

#: #1119's starting count: one kind per extractor pyeye had when #1107 landed.
BASELINE = 11

WHY = "No generic kind can express it: "


def _extractors() -> list[registry.Extractor]:
    return [factory({}) for factory in pyeye_kinds.PYEYE_KINDS.values()]


class TestTheKinds:
    def test_every_pyeye_kind_is_built_in(self) -> None:
        assert pyeye_kinds.PYEYE_KINDS.items() <= kinds.BUILT_IN_KINDS.items()
        assert all(k.startswith(pyeye_kinds.PREFIX) for k in pyeye_kinds.PYEYE_KINDS)

    def test_the_count_only_shrinks(self) -> None:
        """#1119 converts them to generic kinds: a new pyeye-only kind needs a ruling."""
        assert len(pyeye_kinds.PYEYE_KINDS) <= BASELINE

    def test_they_are_pyeyes_extractors_in_order(self) -> None:
        assert [(e.name, e.prefixes) for e in _extractors()] == [
            (e.name, e.prefixes) for e in registry.EXTRACTORS
        ]

    def test_on_pyeyes_repo_they_give_the_registrys_facts(self) -> None:
        assert registry.build(ROOT, _extractors()) == registry.build(ROOT)

    @pytest.mark.parametrize("kind", sorted(pyeye_kinds.PYEYE_KINDS))
    def test_each_says_why_no_generic_kind_can_express_it(self, kind: str) -> None:
        doc = pyeye_kinds.PYEYE_KINDS[kind].__doc__ or ""
        summary, _, why = doc.partition("\n\n")
        assert summary.strip()
        assert why.startswith(WHY)
        assert len(why) > len(WHY) + 20, why

    def test_a_kind_takes_no_options(self) -> None:
        with pytest.raises(kinds.KindOptionsError, match="takes no options; got \\['x'\\]"):
            pyeye_kinds.PYEYE_KINDS["pyeye-edges"]({"x": 1})


def _repo(tmp_path: Path, pyproject: str | None) -> Path:
    if pyproject is not None:
        (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    return tmp_path


class TestTheRestriction:
    @pytest.mark.parametrize(
        ("pyproject", "declared"),
        [
            ('[project]\nname = "other"\n', "declares 'other'"),
            ("[tool.x]\ny = 1\n", "declares no \\[project\\] name"),
            ("[project]\nname = 3\n", "declares no \\[project\\] name"),
            (None, "declares no \\[project\\] name"),
        ],
    )
    def test_elsewhere_it_refuses_naming_the_restriction(
        self, tmp_path: Path, pyproject: str | None, declared: str
    ) -> None:
        extractor = pyeye_kinds.PYEYE_KINDS["pyeye-env"]({})
        with pytest.raises(ExtractionError, match=f"'pyeye-env' is restricted.*{declared}"):
            list(extractor.extract(_repo(tmp_path, pyproject)))

    def test_pyeyes_repo_is_found_by_its_project_name(self) -> None:
        assert pyeye_kinds.project_name(ROOT) == pyeye_kinds.PROJECT_NAME

    def test_the_cli_reports_it(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        root = _repo(
            tmp_path,
            '[project]\nname = "other"\n\n'
            '[[tool.pyeye.docs_facts.extractors]]\nkind = "pyeye-cli"\n',
        )
        assert main(["check"], root=root) == 1
        err = capsys.readouterr().err
        assert "cannot extract the facts" in err
        assert "'pyeye-cli' is restricted to pyeye's own repository" in err
