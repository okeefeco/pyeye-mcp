"""The per-repository docs-facts config: data only, never code (#1091, RFC #1083 step 1).

A repository says what docs-facts checks in ``[tool.pyeye.docs_facts]`` (in
``pyproject.toml``) or under ``"docs_facts"`` in ``.pyeye.json``, which wins.
The config is read from the repository only, never from the user's global pyeye
config. Per the maintainer's rulings (via designer, 2026-11-22, and C19):

- no config is an error: there is nothing to check;
- facts come from BUILT-IN extractor kinds configured by data, which read files
  and never import or run them. Anything that looks like a code reference is
  refused;
- docs are inline tables;
- rules are ``"all"`` (the default) or a list of known rule IDs;
- output paths default to today's ``docs/facts/...``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pyeye.docs_facts import cli, config, rules
from pyeye.docs_facts.facts import ExtractionError, Fact

PAGE = "docs/arch.md"

PYPROJECT = """\
[project]
name = "demo"
version = "1.2.3"
requires-python = ">=3.11"

[tool.pyeye.docs_facts]
changelog = "CHANGES.md"

[[tool.pyeye.docs_facts.facts]]
id = "project.requires_python"
from = "toml"
file = "pyproject.toml"
key = "project.requires-python"

[[tool.pyeye.docs_facts.docs]]
path = "docs/arch.md"
audience = "human"
kind = "prose"
"""


def _repo(tmp_path: Path, pyproject: str = PYPROJECT, page: str = "") -> Path:
    (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    text = page or (
        "# Arch\n\nPython <!-- fact:begin project.requires_python --><!-- fact:end -->.\n"
    )
    (tmp_path / PAGE).write_text(text, encoding="utf-8")
    return tmp_path


class TestWhereTheConfigIs:
    def test_pyproject(self, tmp_path: Path) -> None:
        setup = config.load(_repo(tmp_path))
        assert [e.path for e in setup.docs] == [PAGE]
        assert setup.changelog == "CHANGES.md"

    def test_pyeye_json_wins(self, tmp_path: Path) -> None:
        root = _repo(tmp_path)
        (root / ".pyeye.json").write_text(
            json.dumps({"docs_facts": {"docs": [], "facts": []}}), encoding="utf-8"
        )
        assert config.load(root).docs == ()

    def test_no_config_is_an_error(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
        with pytest.raises(config.ConfigError, match="nothing to check"):
            config.load(tmp_path)

    def test_the_global_config_is_not_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        (home / ".config/pyeye").mkdir(parents=True)
        (home / ".config/pyeye/config.json").write_text(
            json.dumps({"docs_facts": {"docs": []}}), encoding="utf-8"
        )
        monkeypatch.setenv("HOME", home.as_posix())
        repo = tmp_path / "repo"
        repo.mkdir()
        with pytest.raises(config.ConfigError, match="nothing to check"):
            config.load(repo)


class TestOnlyData:
    """Nothing in the config names code to import (C19)."""

    @pytest.mark.parametrize(
        ("extra", "message"),
        [
            ('extractors = ["mypkg.facts:EXTRACTOR"]', "never imports"),  # a code reference
            ('docs_ref = "pkg.mod:DOCS"', "never imports"),
            ("unknown = 1", "unknown key"),
        ],
    )
    def test_code_and_unknown_keys_are_refused(
        self, tmp_path: Path, extra: str, message: str
    ) -> None:
        root = _repo(tmp_path, PYPROJECT.replace('changelog = "CHANGES.md"', extra))
        with pytest.raises(config.ConfigError, match=message):
            config.load(root)

    def test_a_module_attr_value_is_refused_wherever_it_appears(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, PYPROJECT.replace('"pyproject.toml"', '"pkg.mod:VALUE"'))
        with pytest.raises(config.ConfigError, match="never imports"):
            config.load(root)

    @pytest.mark.parametrize("kind", ["python", "import", "call"])
    def test_an_unknown_fact_kind_is_refused(self, tmp_path: Path, kind: str) -> None:
        root = _repo(tmp_path, PYPROJECT.replace('from = "toml"', f'from = "{kind}"'))
        with pytest.raises(config.ConfigError, match="'from' must be one of"):
            config.load(root)


class TestDocs:
    def test_inline_entries(self, tmp_path: Path) -> None:
        entry = config.load(_repo(tmp_path)).docs[0]
        assert (entry.path, entry.audience, entry.kind) == (PAGE, "human", "prose")

    @pytest.mark.parametrize(("field", "bad"), [("audience", "robots"), ("kind", "novel")])
    def test_a_bad_value_names_the_entry(self, tmp_path: Path, field: str, bad: str) -> None:
        good = {"audience": '"human"', "kind": '"prose"'}[field]
        root = _repo(tmp_path, PYPROJECT.replace(f"{field} = {good}", f'{field} = "{bad}"'))
        with pytest.raises(config.ConfigError, match=f"docs\\[0\\].*{field}"):
            config.load(root)


class TestRules:
    def test_all_is_the_default(self, tmp_path: Path) -> None:
        assert config.load(_repo(tmp_path)).rules == rules.RULES

    def test_a_list_selects(self, tmp_path: Path) -> None:
        root = _repo(
            tmp_path,
            PYPROJECT.replace('changelog = "CHANGES.md"', 'rules = ["honest-claims"]'),
        )
        assert [r.id for r in config.load(root).rules] == ["honest-claims"]

    def test_an_unknown_rule_is_refused(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, PYPROJECT.replace('changelog = "CHANGES.md"', 'rules = ["nope"]'))
        with pytest.raises(config.ConfigError, match="unknown rule"):
            config.load(root)


class TestDataFacts:
    """Built-in kinds read a key path from a data file; nothing is imported."""

    def _facts(self, root: Path) -> list[Fact]:
        setup = config.load(root)
        return [f for x in setup.extractors for f in x.extract(root) if isinstance(f, Fact)]

    def test_toml(self, tmp_path: Path) -> None:
        facts = self._facts(_repo(tmp_path))
        assert [(f.id, f.value, f.markdown) for f in facts] == [
            ("project.requires_python", ">=3.11", "`>=3.11`")
        ]

    @pytest.mark.parametrize(
        ("name", "text", "kind"),
        [
            ("data.json", '{"a": {"b": [1, 2]}}', "json"),
            ("data.yaml", "a:\n  b: [1, 2]\n", "yaml"),
        ],
    )
    def test_json_and_yaml(self, tmp_path: Path, name: str, text: str, kind: str) -> None:
        root = _repo(
            tmp_path,
            PYPROJECT.replace('from = "toml"', f'from = "{kind}"')
            .replace('file = "pyproject.toml"', f'file = "{name}"')
            .replace('key = "project.requires-python"', 'key = "a.b"'),
        )
        (root / name).write_text(text, encoding="utf-8")
        facts = self._facts(root)
        assert [(f.value, f.markdown) for f in facts] == [([1, 2], "`1`, `2`")]

    @pytest.mark.parametrize(
        ("old", "new", "message"),
        [
            ('key = "project.requires-python"', 'key = "project.nope"', "no key 'nope'"),
            ('file = "pyproject.toml"', 'file = "missing.toml"', "missing.toml"),
            ('file = "pyproject.toml"', 'file = "../outside.toml"', "outside the repository"),
        ],
    )
    def test_a_miss_fails_loudly(self, tmp_path: Path, old: str, new: str, message: str) -> None:
        root = _repo(tmp_path, PYPROJECT.replace(old, new))
        with pytest.raises((ExtractionError, config.ConfigError), match=message):
            self._facts(root)

    def test_prefixes_are_the_ids_first_segments(self, tmp_path: Path) -> None:
        extractor = config.load(_repo(tmp_path)).extractors[0]
        assert extractor.prefixes == ("project",)


class TestTheCliUsesTheConfig:
    def test_generate_then_check_on_a_configured_repo(self, tmp_path: Path) -> None:
        root = _repo(tmp_path)
        assert cli.main(["generate"], root=root) == 0
        assert "`>=3.11`" in (root / PAGE).read_text(encoding="utf-8")
        assert cli.main(["check"], root=root) == 0

    def test_a_config_error_fails_the_command_cleanly(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _repo(tmp_path, PYPROJECT.replace('changelog = "CHANGES.md"', "unknown = 1"))
        assert cli.main(["check"], root=root) == 1
        assert "unknown key" in capsys.readouterr().err


class TestPaths:
    def test_defaults_are_todays(self, tmp_path: Path) -> None:
        paths = config.load(_repo(tmp_path)).paths
        assert (paths.snapshot, paths.removed, paths.uncovered, paths.review_state) == (
            "docs/facts/facts.json",
            "docs/facts/removed.json",
            "docs/facts/uncovered.json",
            "docs/facts/review-state.json",
        )

    def test_the_outputs_land_where_configured(self, tmp_path: Path) -> None:
        root = _repo(
            tmp_path,
            PYPROJECT + '\n[tool.pyeye.docs_facts.paths]\nsnapshot = "build/facts.json"\n',
        )
        assert cli.main(["generate"], root=root) == 0
        assert (root / "build/facts.json").is_file()
        assert not (root / "docs/facts/facts.json").exists()


class TestBuiltInKinds:
    """``extractors`` tables name a built-in kind and give it options (#1091, #1092)."""

    @pytest.fixture
    def echo(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
        """A registered test kind that records its options and yields one fact."""
        from pyeye.docs_facts import kinds
        from pyeye.docs_facts.registry import Extractor

        seen: list[dict[str, object]] = []

        def factory(options: object) -> Extractor:
            opts = dict(options)  # type: ignore[call-overload]
            if "bad" in opts:
                raise kinds.KindOptionsError("unknown option 'bad'")
            seen.append(opts)
            prefix = str(opts.get("prefix", "echo"))
            return Extractor("echo", (prefix,), lambda _root: iter([Fact(f"{prefix}.n", 1, "`1`")]))

        monkeypatch.setitem(kinds.BUILT_IN_KINDS, "echo", factory)
        return seen

    def _with(self, tmp_path: Path, table: str) -> Path:
        return _repo(tmp_path, PYPROJECT + "\n[[tool.pyeye.docs_facts.extractors]]\n" + table)

    def test_options_reach_the_factory(self, tmp_path: Path, echo: list[dict[str, object]]) -> None:
        root = self._with(tmp_path, 'kind = "echo"\nprefix = "arch"\ninclude = ["pkg/**"]\n')
        setup = config.load(root)
        assert echo == [{"prefix": "arch", "include": ["pkg/**"]}]
        assert [x.name for x in setup.extractors] == ["data", "echo"]

    def test_an_unknown_kind_is_refused(self, tmp_path: Path) -> None:
        root = self._with(tmp_path, 'kind = "nope"\n')
        with pytest.raises(config.ConfigError, match="'nope' isn't built in"):
            config.load(root)

    @pytest.mark.usefixtures("echo")
    def test_a_kinds_option_error_says_where(self, tmp_path: Path) -> None:
        root = self._with(tmp_path, 'kind = "echo"\nbad = 1\n')
        with pytest.raises(config.ConfigError, match=r"extractors\[0\] \(echo\): unknown option"):
            config.load(root)


class TestLiteralKind:
    """``from = "literal"`` reads a module-level constant from source, never importing it."""

    def test_a_settings_default(self, tmp_path: Path) -> None:
        root = _repo(
            tmp_path,
            PYPROJECT
            + '\n[[tool.pyeye.docs_facts.facts]]\nid = "settings.concurrent"\nfrom = "literal"\n'
            'file = "app/settings.py"\nname = "CONCURRENT_REQUESTS"\n',
        )
        (root / "app").mkdir()
        (root / "app/settings.py").write_text("CONCURRENT_REQUESTS = 16\n", encoding="utf-8")
        facts = {
            f.id: f
            for x in config.load(root).extractors
            for f in x.extract(root)
            if isinstance(f, Fact)
        }
        assert (facts["settings.concurrent"].value, facts["settings.concurrent"].markdown) == (
            16,
            "`16`",
        )

    @pytest.mark.parametrize(
        ("fields", "message"),
        [
            ('from = "literal"\nfile = "a.py"\nkey = "X"\n', "'name'"),  # literal needs name
            ('from = "toml"\nfile = "a.toml"\nname = "X"\n', "'key'"),  # data kinds need key
        ],
    )
    def test_each_kind_takes_its_own_field(self, tmp_path: Path, fields: str, message: str) -> None:
        root = _repo(
            tmp_path, PYPROJECT + '\n[[tool.pyeye.docs_facts.facts]]\nid = "x.y"\n' + fields
        )
        with pytest.raises(config.ConfigError, match=message):
            config.load(root)


class TestPreset:
    """``preset = "pyeye"`` selects the engine's built-in pyeye setup, as data (the bridge to #1107)."""

    def _preset(self, tmp_path: Path, body: str) -> Path:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\n\n[tool.pyeye.docs_facts]\n' + body, encoding="utf-8"
        )
        return tmp_path

    def test_selects_pyeyes_setup(self, tmp_path: Path) -> None:
        from pyeye.docs_facts.setup import pyeye_setup

        setup = config.load(self._preset(tmp_path, 'preset = "pyeye"\n'))
        own = pyeye_setup()
        assert (setup.extractors, setup.docs, setup.rules, setup.pages) == (
            own.extractors,
            own.docs,
            own.rules,
            own.pages,
        )

    def test_rules_changelog_and_paths_override(self, tmp_path: Path) -> None:
        setup = config.load(
            self._preset(
                tmp_path,
                'preset = "pyeye"\nrules = ["honest-claims"]\nchangelog = "NEWS.md"\n'
                '[tool.pyeye.docs_facts.paths]\nsnapshot = "build/facts.json"\n',
            )
        )
        assert [r.id for r in setup.rules] == ["honest-claims"]
        assert (setup.changelog, setup.paths.snapshot) == ("NEWS.md", "build/facts.json")

    @pytest.mark.parametrize("key", ["docs", "facts", "extractors"])
    def test_cant_be_mixed_with_what_it_provides(self, tmp_path: Path, key: str) -> None:
        root = self._preset(tmp_path, f'preset = "pyeye"\n{key} = []\n')
        with pytest.raises(config.ConfigError, match=f"can't be combined with.*{key}"):
            config.load(root)

    def test_only_engine_built_ins(self, tmp_path: Path) -> None:
        root = self._preset(tmp_path, 'preset = "mine"\n')
        with pytest.raises(config.ConfigError, match="preset 'mine' isn't built in"):
            config.load(root)


def test_the_cli_refuses_a_repo_with_no_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No more fallback to pyeye's own setup: a foreign repo with no config has nothing to check."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    assert cli.main(["check"], root=tmp_path) == 1
    assert "nothing to check" in capsys.readouterr().err


def test_this_repository_declares_the_preset() -> None:
    root = Path(__file__).resolve().parents[1]
    assert config.find(root) == {
        "preset": "pyeye",
        "changelog": "CHANGELOG.md",
        "reference_only": ["precommit"],
    }
