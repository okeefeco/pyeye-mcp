"""Reference-only fact families and their own snapshot files (#1108).

Some fact families are reference data, not claims prose should make: 28 of
the 32 ``new`` uncovered-fact ledger entries were ``precommit.*``, and #1092's
``arch.*`` family will add thousands. The maintainer's ruling (2026-11-23):

- a family declared **reference-only** (as data) stays out of the uncovered-fact
  ledger, and ``check``/``generate`` say which families are;
- a family may keep its **own snapshot file**, so ``facts.json`` diffs stay
  readable. Its facts leave ``facts.json``; the removed-name record and the
  changed-fact list read every snapshot file together, so moving a family to
  its own file removes nothing.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from pyeye.docs_facts import cli, config, ledger, removed, rules
from pyeye.docs_facts.docs import DocEntry
from pyeye.docs_facts.facts import Fact, code
from pyeye.docs_facts.registry import Extractor
from pyeye.docs_facts.setup import Paths, Setup, pyeye_setup

# ---------------------------------------------------------------------------
# A small foreign repo with two families: app.* (bound) and arch.* (reference)
# ---------------------------------------------------------------------------

PAGE = "docs/arch.md"
ARCH = "docs/facts/arch.json"


def _app(root: Path) -> Iterator[Fact]:
    count = len(list((root / "app").glob("*.py")))
    yield Fact("app.module_count", count, code(str(count)))
    yield Fact("app.unbound", "x", code("x"))


def _arch(root: Path) -> Iterator[Fact]:
    for module in sorted((root / "app").glob("*.py")):
        yield Fact(f"arch.members.app.{module.stem}", [module.stem], code(module.stem))


def _env(root: Path) -> Iterator[Fact]:
    """A name family: a removed ``env.*`` fact is recorded in ``removed.json``."""
    for module in sorted((root / "app").glob("*.py")):
        name = f"APP_{module.stem.upper()}"
        yield Fact(f"env.{name}", name, code(name))


EXTRACTORS = (
    Extractor("app", ("app",), _app),
    Extractor("arch", ("arch",), _arch),
    Extractor("env", ("env",), _env),
)
ENV = "docs/facts/env.json"


def _foreign(
    tmp_path: Path,
    *,
    reference_only: frozenset[str] = frozenset(),
    snapshots: dict[str, str] | None = None,
) -> tuple[Path, Setup]:
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app/a.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / PAGE).write_text(
        "# Map\n\nModules: <!-- fact:begin app.module_count --><!-- fact:end -->.\n",
        encoding="utf-8",
    )
    entry = DocEntry(PAGE, "human", "prose", MappingProxyType({}))
    setup = Setup(
        extractors=EXTRACTORS,
        docs=(entry,),
        rules=rules.RULES,
        pages={},
        changelog=None,
        paths=Paths(snapshots=MappingProxyType(dict(snapshots or {}))),
        reference_only=reference_only,
    )
    return tmp_path, setup


def _uncovered(result: cli.Plan, setup: Setup) -> set[str]:
    data = json.loads(result.outputs[setup.paths.uncovered])
    return set(data["baseline"]) | {row["fact_id"] for row in data["new"]}


def _snapshot(result: cli.Plan, path: str) -> dict[str, Any]:
    facts: dict[str, Any] = json.loads(result.outputs[path])["facts"]
    return facts


# ---------------------------------------------------------------------------
# The ledger skips reference-only families
# ---------------------------------------------------------------------------


class TestTheLedger:
    def test_updated_skips_a_reference_only_family(self) -> None:
        facts = {
            "app.a": Fact("app.a", 1, "1"),
            "precommit.hook.x": Fact("precommit.hook.x", 1, "1"),
            "precommit_ish.y": Fact("precommit_ish.y", 1, "1"),  # a different family
        }

        fresh = ledger.updated(None, facts, set(), reference_only=frozenset({"precommit"}))

        assert fresh.baseline == ("app.a", "precommit_ish.y")

    def test_an_existing_entry_leaves_when_its_family_becomes_reference_only(self) -> None:
        facts = {"app.a": Fact("app.a", 1, "1"), "precommit.x": Fact("precommit.x", 1, "1")}
        old = ledger.Ledger(baseline=("app.a",), new={"precommit.x": "unreleased"})

        kept = ledger.updated(old, facts, set(), reference_only=frozenset({"precommit"}))

        assert (kept.baseline, dict(kept.new)) == (("app.a",), {})

    def test_the_plan_leaves_them_out_and_says_so(self, tmp_path: Path) -> None:
        root, setup = _foreign(tmp_path, reference_only=frozenset({"arch"}))

        result = cli.plan(root, setup=setup)

        assert _uncovered(result, setup) == {"app.unbound", "env.APP_A"}
        assert "reference-only fact families, outside the uncovered-fact ledger: arch" in (
            result.notes
        )

    def test_without_a_declaration_every_family_is_in_the_ledger(self, tmp_path: Path) -> None:
        root, setup = _foreign(tmp_path)

        result = cli.plan(root, setup=setup)

        assert _uncovered(result, setup) == {"app.unbound", "arch.members.app.a", "env.APP_A"}
        assert not any("reference-only" in note for note in result.notes)

    def test_check_prints_the_note(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, setup = _foreign(tmp_path, reference_only=frozenset({"arch"}))
        assert cli.generate(root, setup=setup) == 0
        capsys.readouterr()

        assert cli.check(root, setup=setup) == 0
        assert "reference-only fact families, outside the uncovered-fact ledger: arch" in (
            capsys.readouterr().out
        )


class TestPyeyesOwnSetup:
    def test_precommit_is_reference_only(self) -> None:
        assert "precommit" in pyeye_setup().reference_only

    def test_no_precommit_entry_is_in_the_ledger(self) -> None:
        data = json.loads(Path(ledger.UNCOVERED).read_text(encoding="utf-8"))
        entries = set(data["baseline"]) | {row["fact_id"] for row in data["new"]}

        assert not [i for i in entries if i.startswith("precommit.")]


# ---------------------------------------------------------------------------
# A family's own snapshot file
# ---------------------------------------------------------------------------


class TestOwnSnapshot:
    def test_the_family_moves_to_its_own_file(self, tmp_path: Path) -> None:
        root, setup = _foreign(tmp_path, snapshots={"arch": ARCH})

        result = cli.plan(root, setup=setup)

        assert set(_snapshot(result, setup.paths.snapshot)) == {
            "app.module_count",
            "app.unbound",
            "env.APP_A",
        }
        assert _snapshot(result, ARCH) == {"arch.members.app.a": ["a"]}

    def test_a_change_in_the_family_touches_only_its_file(self, tmp_path: Path) -> None:
        root, setup = _foreign(
            tmp_path, snapshots={"arch": ARCH}, reference_only=frozenset({"arch"})
        )
        assert cli.generate(root, setup=setup) == 0
        main = (root / setup.paths.snapshot).read_text(encoding="utf-8")

        (root / "app/b.py").write_text("Y = 2\n", encoding="utf-8")
        result = cli.plan(root, setup=setup)

        assert result.outputs[setup.paths.snapshot] != main  # app.module_count changed
        assert "arch.members.app.b" in _snapshot(result, ARCH)
        assert "arch.members.app.b" not in _snapshot(result, setup.paths.snapshot)

    def test_moving_a_family_removes_nothing(self, tmp_path: Path) -> None:
        """The removed-name record reads every snapshot file, not facts.json alone."""
        root, before = _foreign(tmp_path)
        assert cli.generate(root, setup=before) == 0
        _, after = _foreign(tmp_path, snapshots={"env": ENV})

        assert cli.generate(root, setup=after) == 0

        assert removed.load(root, after.paths.removed) == []
        assert "env.APP_A" not in _snapshot(cli.plan(root, setup=after), after.paths.snapshot)
        assert cli.check(root, setup=after) == 0

    def test_a_fact_that_leaves_its_own_file_is_recorded_removed(self, tmp_path: Path) -> None:
        root, setup = _foreign(tmp_path, snapshots={"env": ENV})
        assert cli.generate(root, setup=setup) == 0

        (root / "app/a.py").unlink()
        (root / "app/c.py").write_text("Z = 3\n", encoding="utf-8")
        assert cli.generate(root, setup=setup) == 0

        names = [e.fact_id for e in removed.load(root, setup.paths.removed)]
        assert names == ["env.APP_A"]

    def test_the_changed_list_reads_every_snapshot_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, setup = _foreign(tmp_path, snapshots={"arch": ARCH})
        assert cli.generate(root, setup=setup) == 0
        git = ["git", "-C", root.as_posix()]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run(
            [*git, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base"],
            check=True,
        )
        (root / "app/b.py").write_text("Y = 2\n", encoding="utf-8")
        assert cli.generate(root, setup=setup) == 0
        capsys.readouterr()

        assert cli.report_changed(root, "HEAD", setup=setup) == 0

        out = capsys.readouterr().out
        assert "arch.members.app.b" in out and "app.module_count" in out

    @pytest.mark.parametrize(
        ("snapshots", "message"),
        [
            ({"arch": "docs/facts/facts.json"}, "is the main snapshot"),
            ({"arch": "docs/facts/uncovered.json"}, "is the uncovered-fact ledger"),
            ({"arch": ""}, "must name a file"),
            ({"arch": "docs/facts/x.json", "deps": "docs/facts/x.json"}, "share"),
            ({"Arch": "docs/facts/arch.json"}, "isn't a fact family"),
            ({"arch.members": "docs/facts/arch.json"}, "isn't a fact family"),
        ],
    )
    def test_a_bad_map_is_refused(self, snapshots: dict[str, str], message: str) -> None:
        with pytest.raises(ValueError, match=message):
            Paths(snapshots=MappingProxyType(snapshots))


# ---------------------------------------------------------------------------
# Declared as data in a repository's config (#1091)
# ---------------------------------------------------------------------------


def _config(tmp_path: Path, body: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(f"[tool.pyeye.docs_facts]\n{body}\n", encoding="utf-8")
    return tmp_path


class TestConfig:
    def test_reference_only_and_snapshots(self, tmp_path: Path) -> None:
        root = _config(
            tmp_path,
            'reference_only = ["arch", "deps"]\n'
            '[tool.pyeye.docs_facts.paths.snapshots]\narch = "docs/facts/arch.json"',
        )

        setup = config.load(root)

        assert setup.reference_only == frozenset({"arch", "deps"})
        assert dict(setup.paths.snapshots) == {"arch": "docs/facts/arch.json"}

    def test_the_defaults_are_none(self, tmp_path: Path) -> None:
        setup = config.load(_config(tmp_path, 'rules = "all"'))

        assert setup.reference_only == frozenset()
        assert dict(setup.paths.snapshots) == {}

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            ('reference_only = "arch"', "reference_only must be a list"),
            ('reference_only = ["Arch"]', "isn't a fact family"),
            ("[tool.pyeye.docs_facts.paths]\nsnapshots = 3", "snapshots must be a table"),
            (
                '[tool.pyeye.docs_facts.paths.snapshots]\narch = "docs/facts/facts.json"',
                "is the main snapshot",
            ),
        ],
    )
    def test_bad_declarations_are_refused(self, tmp_path: Path, body: str, message: str) -> None:
        with pytest.raises(config.ConfigError, match=message):
            config.load(_config(tmp_path, body))
