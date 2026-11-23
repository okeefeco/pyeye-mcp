"""The doc registry and ``generate``/``check`` end to end (#824).

The completeness test is what closes the ``.rst`` blind spot (#818): a Markdown
file that isn't in pyeye's doc registry (``docs/facts/docs.toml``), and isn't in an excluded
history tree, fails here, so no documentation can sit outside every check.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - runs git with fixed arguments
from pathlib import Path

import pytest

from pyeye.docs_facts import cli, config, docs, pages
from pyeye.docs_facts.docs import DocEntry, entry_for, for_repo, is_excluded, registered_files
from pyeye.docs_facts.extractors import ci
from pyeye.docs_facts.facts import Fact, View, index

ROOT = Path(__file__).parent.parent
#: pyeye's doc registry, from its config (docs/facts/docs.toml, #1107).
DOCS = for_repo(ROOT)


#: Every documentation file type, so a non-Markdown doc tree (the old Sphinx
#: ``.rst``) can't sit outside the registry unseen (#818).
DOC_PATTERNS = ("*.md", "*.rst", "*.mdx", "*.markdown", "docs/*.txt", "docs/**/*.txt")


def _git_docs() -> list[str]:
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(  # nosec B603 - fixed arguments
        [git, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *DOC_PATTERNS],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    # Deleted-but-unstaged files are still listed by --cached; only report real files.
    paths = {p for p in out.decode("utf-8").split("\0") if p}
    return sorted(p for p in paths if (ROOT / p).is_file())


class TestDocRegistry:
    def test_every_doc_file_is_registered(self) -> None:
        unregistered = [p for p in _git_docs() if not is_excluded(p) and entry_for(p, DOCS) is None]

        assert not unregistered, (
            f"Unregistered docs: {unregistered}. Add each to docs/facts/docs.toml "
            "with its audience and kind."
        )

    def test_the_listing_found_the_docs(self) -> None:
        """Guard the listing: an empty one would make the test above pass vacuously."""
        found = _git_docs()

        assert "README.md" in found
        assert "skills/python-explore/SKILL.md" in found

    def test_every_exact_entry_exists(self) -> None:
        assert docs.missing_files(ROOT) == []

    def test_entries_are_unique_and_posix(self) -> None:
        paths = [e.path for e in DOCS]

        assert len(paths) == len(set(paths))
        assert all("\\" not in p and not p.startswith(("/", "./")) for p in paths)

    def test_no_entry_is_in_an_excluded_tree(self) -> None:
        assert [e.path for e in DOCS if is_excluded(e.path)] == []

    def test_reference_pages_are_exactly_the_generated_ones(self) -> None:
        registered = {e.path for e in DOCS if e.kind == "reference"}

        assert registered == set(pages.PAGES)

    def test_an_exact_entry_wins_over_the_pattern(self) -> None:
        readme = entry_for("changes/README.md", DOCS)
        fragment = entry_for("changes/824.fixed.md", DOCS)

        assert readme is not None and readme.kind == "prose"
        assert fragment is not None and fragment.kind == "history"

    def test_the_pattern_names_one_directory_level(self) -> None:
        assert entry_for("changes/sub/824.fixed.md", DOCS) is None

    def test_pattern_expands_to_matches_without_their_own_entry(self, tmp_path: Path) -> None:
        (tmp_path / "changes").mkdir()
        for name in ("README.md", "1.fixed.md", "2.added.md", "notes.txt"):
            (tmp_path / "changes" / name).write_text("x\n", encoding="utf-8")
        registry = (
            DocEntry("changes/README.md", "human", "prose"),
            DocEntry("changes/*.md", "human", "history"),
        )

        found = {p: e.kind for p, e in registered_files(tmp_path, registry)}

        assert found == {
            "changes/1.fixed.md": "history",
            "changes/2.added.md": "history",
            "changes/README.md": "prose",
        }


class TestRepoIsCurrent:
    def test_check_passes_on_the_repo(self, capsys: pytest.CaptureFixture[str]) -> None:
        """As the command runs it: with the repository's own config (#1091, #1108)."""
        code = cli.check(ROOT, setup=config.load(ROOT))

        assert code == 0, capsys.readouterr().out


FACTS = index(
    [
        Fact("x.one", 1, "1"),
        View("x.list", ("x.one",), "- one"),
    ]
)


@pytest.fixture
def tiny_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo with one registered page, and fixed facts and reference pages."""
    (tmp_path / "README.md").write_text(
        "Value: <!-- fact:begin x.one -->0<!-- fact:end -->\n", encoding="utf-8"
    )
    monkeypatch.setattr(pages, "PAGES", {"ref.md": lambda f: f["x.list"].markdown + "\n"})
    monkeypatch.setattr(cli.registry, "build", lambda _root, *_extractors: FACTS)
    monkeypatch.setattr(cli.rules, "RULES", ())  # tested in test_docs_facts_rules
    # The CLI checks only a repository that declares a config (#1091). A built-in
    # page is pyeye's repository's only (#1107), so this one names itself pyeye.
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "pyeye-mcp"\n\n'
        '[tool.pyeye.docs_facts]\npages = ["ref.md"]\n\n'
        '[[tool.pyeye.docs_facts.docs]]\npath = "README.md"\naudience = "human"\nkind = "prose"\n\n'
        '[[tool.pyeye.docs_facts.docs]]\npath = "ref.md"\naudience = "both"\nkind = "reference"\n',
        encoding="utf-8",
    )
    return tmp_path


class TestGenerateAndCheck:
    def test_check_fails_until_generate_runs(
        self, tiny_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.check(tiny_repo) == 1
        # README, the reference page, the snapshot, the removed names and the ledger (#826)
        assert "5 file(s) differ" in capsys.readouterr().out

        assert cli.generate(tiny_repo) == 0
        assert (tiny_repo / "README.md").read_text(encoding="utf-8") == (
            "Value: <!-- fact:begin x.one -->1<!-- fact:end -->\n"
        )
        assert (tiny_repo / "ref.md").read_text(encoding="utf-8") == "- one\n"
        assert '"x.one": 1' in (tiny_repo / cli.SNAPSHOT).read_text(encoding="utf-8")

        assert cli.check(tiny_repo) == 0
        capsys.readouterr()
        assert cli.generate(tiny_repo) == 0
        assert "regenerated" not in capsys.readouterr().out

    def test_a_hand_edit_inside_a_block_fails_check(
        self, tiny_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli.generate(tiny_repo)
        readme = tiny_repo / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8").replace("->1<", "->2<"), "utf-8")
        capsys.readouterr()

        assert cli.check(tiny_repo) == 1
        out = capsys.readouterr().out
        assert "-Value: <!-- fact:begin x.one -->2<!-- fact:end -->" in out
        assert "+Value: <!-- fact:begin x.one -->1<!-- fact:end -->" in out

    def test_an_unknown_id_fails_both(
        self, tiny_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli.generate(tiny_repo)
        (tiny_repo / "README.md").write_text(
            "<!-- fact:begin x.gone -->\n<!-- fact:end -->\n", encoding="utf-8"
        )

        assert cli.generate(tiny_repo) == 1
        assert "README.md:1: unknown fact ID 'x.gone'" in capsys.readouterr().err
        assert cli.check(tiny_repo) == 1
        assert "README.md:1: unknown fact ID 'x.gone'" in capsys.readouterr().out

    def test_a_missing_registered_file_fails(
        self, tiny_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli.generate(tiny_repo)
        (tiny_repo / "README.md").unlink()

        assert cli.check(tiny_repo) == 1
        assert "README.md: registered in the doc registry but missing" in capsys.readouterr().out

    def test_main_dispatches(self, tiny_repo: Path) -> None:
        assert cli.main(["generate", "--root", tiny_repo.as_posix()]) == 0
        assert cli.main(["check"], root=tiny_repo) == 0

    def test_long_diffs_are_cut(self, tiny_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
        cli.generate(tiny_repo)
        (tiny_repo / "ref.md").write_text("".join(f"{i}\n" for i in range(100)), "utf-8")
        capsys.readouterr()

        assert cli.check(tiny_repo) == 1
        assert "more diff lines" in capsys.readouterr().out

    def test_an_extraction_error_fails_main_cleanly(
        self, tiny_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def disagree(_root: Path, *_extractors: object) -> None:
            raise ci.ExtractionError("ci.yml uses --cov-fail-under [80], pyproject 85")

        monkeypatch.setattr(cli.registry, "build", disagree)

        assert cli.main(["check"], root=tiny_repo) == 1
        assert cli.main(["generate"], root=tiny_repo) == 1
        assert "cannot extract the facts: ci.yml uses" in capsys.readouterr().err
