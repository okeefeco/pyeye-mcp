"""The inline config path, dogfooded in CI on a small fixture repository (#1091).

``tests/fixtures/docs_facts_inline`` configures docs-facts inline, as a
repository other than pyeye does: ``literal``, ``toml``, ``json`` and ``yaml``
facts bound into one page, and ``rules = ["honest-claims"]``. Its generated
records are committed, so ``check`` must pass on it as it stands, and every
kind must catch a change to what it reads.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pyeye.docs_facts import cli

FIXTURE = Path(__file__).parent / "fixtures" / "docs_facts_inline"
PAGE = "docs/overview.md"


def test_check_passes_on_the_fixture() -> None:
    assert cli.main(["check"], root=FIXTURE) == 0


def test_the_page_shows_every_kinds_value() -> None:
    page = (FIXTURE / PAGE).read_text(encoding="utf-8")
    for shown in ("`>=3.11`", "`30`", "`memory`, `disk`", "`ap-southeast-2`", "`4`"):
        assert shown in page


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    return Path(shutil.copytree(FIXTURE, tmp_path / "repo"))


@pytest.mark.parametrize(
    ("file", "old", "new"),
    [
        ("app/settings.py", "TIMEOUT = 30", "TIMEOUT = 45"),  # literal
        ("pyproject.toml", 'requires-python = ">=3.11"', 'requires-python = ">=3.12"'),  # toml
        ("app/deploy.json", "ap-southeast-2", "eu-west-1"),  # json
        ("app/workers.yaml", "size: 4", "size: 8"),  # yaml
    ],
)
def test_a_change_to_what_a_kind_reads_is_stale(copy: Path, file: str, old: str, new: str) -> None:
    path = copy / file
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    assert cli.main(["check"], root=copy) == 1
    assert cli.main(["generate"], root=copy) == 0
    assert cli.main(["check"], root=copy) == 0


def test_honest_claims_runs_on_it(copy: Path, capsys: pytest.CaptureFixture[str]) -> None:
    page = copy / PAGE
    page.write_text(page.read_text(encoding="utf-8") + "\nIt is 40% faster.\n", encoding="utf-8")
    assert cli.main(["check"], root=copy) == 1
    assert "honest-claims" in capsys.readouterr().out


def test_no_pyeye_page_or_rule_runs_on_it() -> None:
    result = cli.plan(FIXTURE, setup=cli.config.load(FIXTURE))
    assert not any(path.startswith("docs/reference/") for path in result.outputs)
    assert result.notes == []  # only honest-claims was selected, and it needs no facts
