"""The docs site publishes the doc registry's pages, at their repo paths (#861)."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from pyeye.docs_facts import site
from pyeye.docs_facts.docs import DocEntry, for_repo, registered_files

ROOT = Path(__file__).parent.parent
#: pyeye's doc registry, from its config (docs/facts/docs.toml, #1107).
DOCS = for_repo(ROOT)


def _flatten(nav: list[Any]) -> list[str]:
    out: list[str] = []
    for item in nav:
        if isinstance(item, str):
            out.append(item)
        else:
            for child in item.values():
                out.extend(_flatten(child))
    return out


@pytest.fixture(scope="module")
def pages() -> list[str]:
    return site.published(ROOT)


_seeded_history = DocEntry(
    "docs/old.md", "human", "history", MappingProxyType({"honest-claims": ("unbacked x",)})
)


class TestWhatIsPublished:
    def test_home_first_and_the_reference_pages_in(self, pages: list[str]) -> None:
        assert pages[0] == "README.md"
        assert {"docs/reference/tools.md", "docs/reference/env-vars.md"} <= set(pages)
        assert {"CONTRIBUTING.md", "docs/TROUBLESHOOTING.md"} <= set(pages)

    def test_claude_files_skills_and_plumbing_stay_out(self, pages: list[str]) -> None:
        entries = dict(registered_files(ROOT))
        for path in pages:
            entry = entries[path]
            assert entry.audience in ("human", "both"), path
            assert entry.kind != "skill", path
        assert ".github/pull_request_template.md" not in pages
        assert ".claude/README.md" not in pages
        assert not [p for p in pages if p.startswith("changes/")]

    def test_history_is_published_exactly_when_its_seeds_are_gone(self, pages: list[str]) -> None:
        """C16: a history page waits while it has honest-claims seeds, then publishes.

        #830 cleared the four held-back pages, so they're on the site now; any
        history page that still has seeds stays off.
        """
        history = [
            (path, entry)
            for path, entry in registered_files(ROOT)
            if entry.kind == "history" and entry.site is None
        ]
        assert history, "no history pages registered: the check would be vacuous"
        for path, entry in history:
            assert (path in pages) is (not entry.allow.get("honest-claims")), path
        assert {"CHANGELOG.md", "docs/migration-guide.md", "docs/api-redesign.md"} <= set(pages)

    @pytest.mark.parametrize(
        ("entry", "published"),
        [
            (DocEntry("docs/x.md", "human", "prose"), True),
            (DocEntry("docs/x.md", "both", "reference"), True),
            (DocEntry("docs/x.md", "claude", "prose"), False),
            (DocEntry("skills/x/SKILL.md", "claude", "skill"), False),
            (DocEntry("docs/old.md", "human", "history"), True),
            (_seeded_history, False),
            (DocEntry("docs/x.md", "human", "prose", site=False), False),
            (DocEntry("docs/x.md", "claude", "prose", site=True), True),
            (DocEntry("docs/old.md", "human", "history", _seeded_history.allow, site=True), True),
        ],
    )
    def test_the_rule(self, entry: DocEntry, published: bool) -> None:
        assert site.is_published(entry) is published

    def test_overrides_live_on_the_entries(self) -> None:
        """No list of paths in the generator: every exception is a `site` on an entry."""
        source = Path(site.__file__).read_text(encoding="utf-8")

        assert ".github" not in source and "changes/" not in source

    def test_only_registered_pages(self, tmp_path: Path) -> None:
        """A Markdown file outside the registry never reaches the site."""
        (tmp_path / "README.md").write_text("# Home\n", encoding="utf-8")
        (tmp_path / "stray.md").write_text("# Stray\n", encoding="utf-8")
        docs = (DocEntry("README.md", "human", "prose", MappingProxyType({})),)

        assert site.published(tmp_path, docs) == ["README.md"]


class TestNav:
    def test_the_nav_is_exactly_the_published_pages(self, pages: list[str]) -> None:
        assert sorted(_flatten(site.nav(pages))) == sorted(pages)

    def test_a_folders_readme_leads_its_section(self) -> None:
        nav = site.nav(["README.md", "docs/a.md", "docs/README.md", "docs/api/README.md"])

        assert nav == [
            "README.md",
            {"Docs": ["docs/README.md", "docs/a.md", {"Api": ["docs/api/README.md"]}]},
        ]

    def test_mkdocs_yml_lists_no_pages(self) -> None:
        """No parallel list of files: the nav comes only from the registry (#818)."""
        config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")

        assert not [line for line in config.splitlines() if line.startswith("nav:")]
        assert "scripts/mkdocs_hooks.py" in config


REPO = "https://github.com/okeefeco/pyeye-mcp"


class TestLinks:
    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "guide.md").write_text("x", encoding="utf-8")
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "rules.md").write_text("x", encoding="utf-8")
        (tmp_path / "src").mkdir()
        return tmp_path

    SITE = frozenset({"README.md", "docs/guide.md"})

    @pytest.mark.parametrize(
        ("page", "href", "expected"),
        [
            ("README.md", ".claude/rules.md", f"{REPO}/blob/main/.claude/rules.md"),
            ("docs/guide.md", "../.claude/rules.md#x", f"{REPO}/blob/main/.claude/rules.md#x"),
            ("README.md", "src/", f"{REPO}/tree/main/src"),
            ("README.md", "docs/guide.md", None),  # published: MkDocs handles it
            ("README.md", "docs/missing.md", None),  # missing: --strict reports it
            ("README.md", "https://example.org", None),
            ("README.md", "#section", None),
            ("README.md", "mailto:a@example.org", None),
        ],
    )
    def test_github_link(self, repo: Path, page: str, href: str, expected: str | None) -> None:
        assert site.github_link(page, href, repo, self.SITE, REPO) == expected

    def test_rewrite_leaves_code_alone(self, repo: Path) -> None:
        text = (
            "See [rules](.claude/rules.md).\n\n"
            "`[rules](.claude/rules.md)`\n\n"
            "```markdown\n[rules](.claude/rules.md)\n```\n"
        )

        out = site.rewrite_links(text, "README.md", repo, self.SITE, REPO)

        assert out.count(f"{REPO}/blob/main/.claude/rules.md") == 1
        assert out.count("(.claude/rules.md)") == 2

    def test_images_are_left_alone(self, repo: Path) -> None:
        text = "![diagram](.claude/rules.md)\n"

        assert site.rewrite_links(text, "README.md", repo, self.SITE, REPO) == text

    def test_the_repository_url_comes_from_pyproject(self) -> None:
        assert site.repository_url(ROOT) == REPO


def test_every_registry_entry_is_considered() -> None:
    """The site reads the registry through registered_files, so it sees the same pages."""
    assert {p for p, _ in registered_files(ROOT)} >= set(site.published(ROOT))
    assert len(DOCS) > 0
