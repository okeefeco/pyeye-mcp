---
date: "2026-11-18"
title: "The resolver's strategy chain and bare-name policy are tables the code runs and the docs bind (#830)"
issues: [830, 818]
anchors: ["pyeye.resolver.STRATEGY", "pyeye.resolver.PROJECT_STRATEGY", "pyeye.resolver.EXTERNAL_STRATEGY", "pyeye.resolver.BARE_NAME_POLICY", "pyeye.resolver._resolve", "pyeye.resolver.resolve_name", "pyeye.docs_facts.extractors.resolver", "tests/test_docs_facts_resolver.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-18 — The resolver's strategy chain and bare-name policy are tables the code runs and the docs bind (#830)

**Friction:** `docs/architecture/resolution.md` restated the resolver's strategy chain and bare-name policy step by step. The copy had already drifted from the code: it left out the static private-stdlib step (#544) and numbered the external steps in a different order from the one they run in. The code's own record of the order was prose too, in the `pyeye.resolver` module docstring, with inline `# 1` … `# 6` comments. That gave three hand-kept copies. Under C15 (prose must not state code facts), the page has to bind the order, and a docstring isn't a stable source to bind.

**Decision:**

- **The order is data.** `_resolve` runs `STRATEGY` (every path), then `PROJECT_STRATEGY` or `EXTERNAL_STRATEGY`, picked by the path's top-level package only after the shared steps miss. That keeps the original control flow and its cost. Each entry is a `Step(name, summary, run)`. `resolve_name` runs `BARE_NAME_POLICY`, a tuple of `NameRule(name, summary, run)`. The first entry that answers wins in both.
- **One copy of the order.** The extractor `pyeye.docs_facts.extractors.resolver` turns each step and rule into a fact (`resolver.strategy.<step>`, `resolver.bare_name.<rule>`) with its side, its position and its summary. `resolution.md` binds the two views. The module docstring and `resolve_name`'s docstring now point at the tables instead of restating them.
- **Behaviour is unchanged.** The external steps share one lazily-run synthetic import (`_Inference`), so `_synthetic_import` still runs at most once per path, and only if an inferring step is reached. `tests/test_docs_facts_resolver.py` records the order in which `_resolve` and `resolve_name` call the table entries, and checks that the first answer wins.
- **Rejected:**
  - Binding the docstrings: they're prose and had drifted already.
  - Concepts plus a link only: the user chose facts.
  - Keeping hand-written lists: they break C15.

**Anchor:** `pyeye.resolver.STRATEGY` / `PROJECT_STRATEGY` / `EXTERNAL_STRATEGY` / `BARE_NAME_POLICY`, `pyeye.resolver._resolve`, `pyeye.resolver.resolve_name`; `pyeye.docs_facts.extractors.resolver`; design `docs/superpowers/specs/2026-11-17-docs-built-on-facts-design.md` C15; #830, #818.
**Applies-to:**

- the resolver's chain and policy: `pyeye.resolver._resolve`, `pyeye.resolver.resolve_name` and their four tables;
- the docs that show them: `docs/architecture/resolution.md` (the `resolver.strategy` and `resolver.bare_name` blocks).

**Verify:** GOLD. `uv run pytest tests/test_docs_facts_resolver.py` checks the call order, first-answer-wins and the facts. The resolver suites (`-k "resolve or resolver or stdlib or reexport or canonical or namespace"`) pass unchanged, and `uv run python scripts/docs_facts.py check` passes.
