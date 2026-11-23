"""The generic ``entry-points`` kind: console scripts and ``python -m`` modules (#1119).

It replaced ``pyeye-cli``: any repository with a ``[project.scripts]`` table or
a package with a ``__main__.py`` can name it. Tested on a fixture repository
and on pyeye's own, where its facts are the ones ``pyeye-cli`` gave.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pyeye.docs_facts import config, entry_points, kinds, registry
from pyeye.docs_facts.facts import Bindable, ExtractionError, Fact, View

ROOT = Path(__file__).resolve().parent.parent

PYPROJECT = """\
[project]
name = "acme"

[project.scripts]
zeta = "acme.cli:main"
alpha = "acme.tools:run"
"""


def _repo(tmp_path: Path, pyproject: str | None = PYPROJECT) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    if pyproject is not None:
        (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    package = tmp_path / "src" / "acme"
    for rel in ("__init__.py", "__main__.py", "tools/__init__.py", "tools/__main__.py"):
        (package / rel).parent.mkdir(parents=True, exist_ok=True)
        (package / rel).write_text("", encoding="utf-8")
    (package / "plain.py").write_text("", encoding="utf-8")
    return tmp_path


def _build(root: Path, **options: object) -> dict[str, Bindable]:
    return registry.build(root, [kinds.BUILT_IN_KINDS["entry-points"](options)])


class TestOnAFixtureRepo:
    def test_scripts_and_modules(self, tmp_path: Path) -> None:
        built = _build(_repo(tmp_path), package="src/acme")
        assert built["cli.script.alpha"] == Fact(
            "cli.script.alpha", {"target": "acme.tools:run"}, "`alpha`"
        )
        assert built["cli.module.acme"] == Fact(
            "cli.module.acme", {"command": "python -m acme"}, "`python -m acme`"
        )
        assert sorted(built) == [
            "cli.all",
            "cli.module.acme",
            "cli.module.acme.tools",
            "cli.script.alpha",
            "cli.script.zeta",
        ]

    def test_the_view_tables_them_scripts_first(self, tmp_path: Path) -> None:
        view = _build(_repo(tmp_path), package="src/acme")["cli.all"]
        assert isinstance(view, View)
        assert view.members == (
            "cli.script.alpha",
            "cli.script.zeta",
            "cli.module.acme",
            "cli.module.acme.tools",
        )
        assert view.markdown.splitlines() == [
            "| Command | Kind | Runs |",
            "|---|---|---|",
            "| `alpha` | console script | `acme.tools:run` |",
            "| `zeta` | console script | `acme.cli:main` |",
            "| `python -m acme` | module | `acme` |",
            "| `python -m acme.tools` | module | `acme.tools` |",
        ]

    def test_prefix_and_module_name_are_options(self, tmp_path: Path) -> None:
        built = _build(_repo(tmp_path), package="src/acme", module="acme_app", prefix="entry")
        assert "entry.module.acme_app.tools" in built
        assert built["entry.module.acme_app"].value == {"command": "python -m acme_app"}
        assert "entry.script.zeta" in built and "entry.all" in built

    def test_no_scripts_table_gives_modules_only(self, tmp_path: Path) -> None:
        built = _build(_repo(tmp_path, '[project]\nname = "acme"\n'), package="src/acme")
        assert not [k for k in built if k.startswith("cli.script.")]
        assert "cli.module.acme" in built

    def test_no_package_gives_scripts_only(self, tmp_path: Path) -> None:
        built = _build(_repo(tmp_path))
        assert sorted(built) == ["cli.all", "cli.script.alpha", "cli.script.zeta"]

    @pytest.mark.parametrize(
        ("pyproject", "message"),
        [
            (None, "has no pyproject.toml"),
            ("[tool.x]\ny = 1\n", "has no \\[project\\] table"),
            ('[project]\nscripts = "x"\n', "\\[project.scripts\\] must be a table of strings"),
        ],
    )
    def test_a_missing_or_malformed_pyproject_fails_loudly(
        self, tmp_path: Path, pyproject: str | None, message: str
    ) -> None:
        with pytest.raises(ExtractionError, match=message):
            _build(_repo(tmp_path, pyproject), package="src/acme")

    def test_a_missing_package_fails_loudly(self, tmp_path: Path) -> None:
        with pytest.raises(ExtractionError, match="'src/nope' isn't a directory"):
            _build(_repo(tmp_path), package="src/nope")

    def test_a_package_outside_the_repo_is_refused(self, tmp_path: Path) -> None:
        root = _repo(tmp_path / "repo")
        (tmp_path / "elsewhere").mkdir()
        with pytest.raises(ExtractionError, match="outside the repository"):
            _build(root, package="../elsewhere")


class TestOptions:
    @pytest.mark.parametrize(
        ("options", "message"),
        [
            ({"x": 1}, "unknown option\\(s\\) \\['x'\\]"),
            ({"package": 3}, "'package' must be a non-empty string"),
            ({"package": ""}, "'package' must be a non-empty string"),
            ({"prefix": "a.b"}, "'prefix' must be one ID segment"),
            ({"module": "acme"}, "'module' needs 'package'"),
        ],
    )
    def test_bad_options_are_refused(self, options: dict[str, object], message: str) -> None:
        with pytest.raises(kinds.KindOptionsError, match=message):
            kinds.BUILT_IN_KINDS["entry-points"](options)

    def test_it_owns_its_prefix(self) -> None:
        extractor = kinds.BUILT_IN_KINDS["entry-points"]({"prefix": "entry"})
        assert (extractor.name, extractor.prefixes) == ("entry", ("entry",))

    def test_it_runs_on_any_repository(self, tmp_path: Path) -> None:
        """Not restricted like the ``pyeye-*`` kinds: the fixture declares ``acme``."""
        assert not entry_points.KIND.startswith("pyeye-")
        assert _build(_repo(tmp_path), package="src/acme")


class TestOnPyeye:
    def _configured(self) -> registry.Extractor:
        (extractor,) = [e for e in config.load(ROOT).extractors if e.name == "cli"]
        return extractor

    def test_pyeyes_config_names_it(self) -> None:
        raw = config.find(ROOT)
        assert raw is not None
        assert {"kind": "entry-points", "package": "src/pyeye"} in raw["extractors"]

    def test_it_gives_the_committed_facts(self) -> None:
        """Byte-identical to what ``pyeye-cli`` gave: the committed values and view."""
        built = registry.build(ROOT, [self._configured()])
        committed = json.loads((ROOT / "docs/facts/facts.json").read_text(encoding="utf-8"))
        assert {k: v.value for k, v in built.items() if isinstance(v, Fact)} == {
            k: v for k, v in committed["facts"].items() if k.startswith("cli.")
        }
        assert {k: list(v.members) for k, v in built.items() if isinstance(v, View)} == {
            k: v for k, v in committed["views"].items() if k.startswith("cli.")
        }
