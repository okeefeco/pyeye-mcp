---
date: "2026-11-17"
title: "Sphinx is retired; Markdown under docs/ is the only docs tree (#823)"
issues: [823, 818]
anchors: ["docs/architecture/resolution.md", "docs/architecture/plugin-system.md", "docs/architecture/caching.md", "tests/test_sphinx_retired.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-17 — Sphinx is retired; Markdown under docs/ is the only docs tree (#823)

**Friction:** The #818 sweep of the docs found 183 findings, and many were in the Sphinx tree (`docs/source/**`). That tree duplicated the README, CONTRIBUTING and `docs/`, and it still taught the v1 API (`find_symbol`, `find_models`, a `FastMCP` server, planned dynamic plugin loading). It drifted unseen because the doc checks (the removed-tool guard and others) scan Markdown only, so `.rst` was a blind spot. Building it needed a `docs` dependency group, a Pages workflow and a Dependabot group, all kept current for a site that was wrong.

**Decision:**

- **One docs tree: Markdown under `docs/`.** `docs/source/**`, `docs/Makefile`, `.github/workflows/build-deploy-docs.yml`, the `docs` dependency group (`pyproject.toml`, `uv.lock`) and Dependabot's `sphinx*` / `myst-parser` patterns are deleted. There is no published docs site (#818 non-goal). Unpublishing GitHub Pages is a repo setting, left to the maintainer.
- **Port only what is still true.** `resolution.rst` (current, and linked from the shipped `python-explore` skill) became `docs/architecture/resolution.md`. Its parso line was corrected: since #713, eviction is recovered and the cache is LRU-bounded, not "never garbage-collected". The still-correct parts of `plugin-system.rst` and `caching-strategy.rst` were checked against the code and rewritten as `docs/architecture/plugin-system.md` and `docs/architecture/caching.md`. The v1 tool names, the made-up plugin code samples, dynamic loading and the old `CodebaseWatcher` sample were dropped rather than ported. Every other page was deleted, because what it covered is in the README, CONTRIBUTING or `docs/`.
- **Rejected: keep Sphinx and extend the checks to `.rst`.** That keeps two trees to bind to facts (#818 D2) and doubles the surface for the "parallel list of files" anti-goal.

**Anchor:** #823, #818 (D1, §7); `docs/architecture/resolution.md`, `docs/architecture/plugin-system.md`, `docs/architecture/caching.md`; `tests/test_sphinx_retired.py`.
**Applies-to:** none (a docs-tree policy: it governs where documentation lives, not a code site).

**Verify:** gold. `uv run pytest tests/test_sphinx_retired.py` passes: no `docs/source`, `docs/Makefile` or docs workflow; no `.rst` under `docs/`; no `docs` dependency group and no Sphinx/MyST requirement in `pyproject.toml`; no Sphinx or MyST package in `uv.lock` or `.github/dependabot.yml`; the three ported pages exist, are linked from `DOCUMENTATION.md`, and their relative links resolve; the `python-explore` skill links `docs/architecture/resolution.md`, not `docs/source`. The Pages unpublish is unverifiable in-repo (a repo setting).
