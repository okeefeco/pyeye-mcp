"""Sphinx is retired; Markdown under ``docs/`` is the only docs tree (#823, #818 D1, amended by #861).

The ``.rst`` tree drifted unseen because the doc checks scanned only Markdown.
These tests keep a second docs tree, and the tooling that built it, from coming
back, and keep the ported architecture pages linked from where readers arrive.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_ARCHITECTURE = _ROOT / "docs" / "architecture"


def test_no_sphinx_tree():
    """``docs/source``, its Makefile and its deploy workflow are gone."""
    assert not (_ROOT / "docs" / "source").exists()
    assert not (_ROOT / "docs" / "Makefile").exists()
    assert not (_ROOT / ".github" / "workflows" / "build-deploy-docs.yml").exists()


def test_no_rst_docs():
    """No reStructuredText page survives anywhere under ``docs/``."""
    rst = sorted(p.relative_to(_ROOT).as_posix() for p in (_ROOT / "docs").rglob("*.rst"))
    assert not rst, f"docs are Markdown only (#823): {rst}"


def test_no_sphinx_dependency():
    """No Sphinx package survives, and the ``docs`` group is only the MkDocs site.

    #861 amends D1: the Markdown is published again, with MkDocs. The ``docs``
    group came back for that site, holding MkDocs and its theme, never Sphinx.
    """
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    groups = pyproject.get("dependency-groups", {})
    requirements = [req for group in groups.values() for req in group if isinstance(req, str)]
    assert not [req for req in requirements if re.match(r"(?i)sphinx|myst", req)]
    site = [req for req in groups.get("docs", []) if isinstance(req, str)]
    assert all(re.match(r"mkdocs", req) for req in site), site


def test_no_sphinx_in_lock_or_dependabot():
    """``uv.lock`` holds no Sphinx package, and Dependabot no longer groups one."""
    lock = (_ROOT / "uv.lock").read_text(encoding="utf-8")
    assert not re.search(r'^name = "(sphinx|myst-parser)', lock, re.M)
    dependabot = (_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert "sphinx" not in dependabot.lower()
    assert "myst" not in dependabot.lower()


@pytest.mark.parametrize("page", ["resolution.md", "plugin-system.md", "caching.md"])
def test_architecture_pages_ported(page: str):
    """The pages ported from the Sphinx tree exist as Markdown and are linked."""
    assert (_ARCHITECTURE / page).is_file()
    index = (_ROOT / "DOCUMENTATION.md").read_text(encoding="utf-8")
    assert f"(docs/architecture/{page})" in index


def test_python_explore_links_the_markdown_resolution_page():
    """The shipped skill links the ported page, not the deleted ``.rst`` one."""
    skill = (_ROOT / ".claude" / "skills" / "python-explore" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "docs/source" not in skill
    assert "docs/architecture/resolution.md" in skill


def test_architecture_relative_links_resolve():
    """Every relative link between the architecture pages points at a real file."""
    broken = []
    for page in sorted(_ARCHITECTURE.glob("*.md")):
        for target in re.findall(r"\]\(([^)#:]+)(?:#[^)]*)?\)", page.read_text(encoding="utf-8")):
            if not (page.parent / target).exists():
                broken.append(f"{page.name} -> {target}")
    assert not broken, broken
