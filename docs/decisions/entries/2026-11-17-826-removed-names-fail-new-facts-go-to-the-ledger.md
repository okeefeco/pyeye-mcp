---
date: "2026-11-17"
title: "A removed name in live prose fails; a newly uncovered fact goes to a non-blocking ledger (#826)"
issues: [826, 818]
anchors: ["pyeye.docs_facts.removed.updated", "pyeye.docs_facts.removed.mentions", "pyeye.docs_facts.ledger.updated", "pyeye.docs_facts.changed.diff", "pyeye.docs_facts.cli.plan", "scripts/changelog.py", "tests/test_docs_facts_removed.py", "tests/test_docs_facts_ledger.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-17 — A removed name in live prose fails; a newly uncovered fact goes to a non-blocking ledger (#826)

**Friction:** #824's binding catches a removed fact only while a marker block still names it. Prose that names a removed tool outside a block passed unnoticed, which is how the v1 tools survived in `docs/api/` and `DOCUMENTATION.md` through three removal passes. The one guard that did exist (#509, in `tests/test_mcp_surface_conformance.py`) kept its own hand-written name sets, a private glob over `.md` and `.json`, and page-wide exemptions for nine paths. A page-wide exemption is blind to a new wrong mention on that page. Separately, a fact added to the code with no prose explaining it was invisible.

**Decision:**

- **One record of removals.** `docs/facts/removed.json` has one entry per removed fact ID. `generate` appends every tool, parameter, env var, entry point or edge that leaves the committed snapshot, in the same PR, with `removed_in: "unreleased"`. `scripts/changelog.py prepare` stamps the release over it. Entries are never deleted. Value facts (`ci.*`, `ceiling.*`, `project.*`) have no name, so they aren't recorded. Seeded with #509's names. Each seeded `removed_in` was checked against the release tags by AST: `find_symbol_multi`, `configure_namespace_package` and `find_in_namespace` were last in 1.1.1, and the rest were last in 1.1.2. `lookup` was never in a release, and its note says so (D12). The names #556 and #553 rejected (`PYEYE_PACKAGES`, `uv run pyeye` and others) were never read or never worked, so they aren't "removed". #825's rules keep rejecting them.
- **Matching (design C8 Q1).** Each entry's `match` is `word` (any mention fails; the default for tools, env vars and entry points), `heading` (only an API heading fails, for names that live on as `JediAnalyzer` methods, such as `find_symbol`), `code` (only a mention in inline code fails; the default for edges, whose names are common words, so a skill saying "use the `callers` edge" after its removal still fails, C10) or `none` (recorded, not scanned; the default for parameters). `match` is the only hand-edited field.
- **Live pages (C8 Q2).** On a `prose` or `skill` page, a line naming a removed name passes only if it also says "removed". Each such mention must also be listed in the page's `DocEntry.allow["removed-name"]` by its exact, line-number-free message (`names removed tool 'find_references' beside 'removed'`). The list only shrinks, and #837's `rules.ratchet` compares it as a multiset. Exact messages rather than a line count mean a fix can't be traded for a new mention, and one allowed line can't cover new names (#837's review). From the next major release after `removed_in`, any match fails, and only `history` pages may name it. The current major is the newest release heading in `CHANGELOG.md`, not the scm version, so the v3.0.0 release PR fails, rather than `main` after the tag. A name that becomes a live fact again isn't scanned.
- **Surface tests (C8 Q3).** `REMOVED_TOOLS` is read from `removed.json`. #509's prose class, its name sets and its path allow-list are deleted. The analyzer-method and module checks keep their own lists.
- **The ledger (D5, C3).** `generate` writes `docs/facts/uncovered.json`. A fact is covered when a `prose` or `skill` page shows it in a marker block or lists it in its entry's `covers` (C10 Q5). A link to `docs/reference/` doesn't count. The facts uncovered on day one are the `baseline` section, which only shrinks and is triaged in #831. Later ones are `new` entries with `first_seen`. The ledger never fails a check.
- **The changed-fact list (§3, C4).** `docs_facts changed --base REV` diffs the snapshot against REV's and maps each fact to the pages that bind it. CI writes it to the job summary on PRs, and it never fails.
- **Rejected:**
  - Seeding the never-existed env names and commands, which would assert a false `removed_in` (D12).
  - Per-page exemptions, which hid drift before.
  - Reading the sunset from the scm version, which would break `main` after the tag instead of the release PR.
  - Counting a reference-page link as coverage, which would make the ledger empty.

**Anchor:** `pyeye.docs_facts.removed` (`updated`, `mentions`, `sunset_passed`); `pyeye.docs_facts.ledger.updated`; `pyeye.docs_facts.changed.diff`; `pyeye.docs_facts.cli.plan`; `scripts/changelog.py` `stamp_fact_ledgers`; design `docs/superpowers/specs/2026-11-17-docs-built-on-facts-design.md` D4, D5, C1–C3, C8 (#832), C10; #826, #818.
**Applies-to:**

- the record and its writer: `docs/facts/removed.json`, `pyeye.docs_facts.removed.updated`, `pyeye.docs_facts.cli.plan`;
- the rule: `pyeye.docs_facts.removed.mentions` over `pyeye.docs_facts.docs.DOCS` entries of kind `prose` and `skill`, with `DocEntry.allow["removed-name"]`;
- the surface tests: `REMOVED_TOOLS` in `tests/test_mcp_surface_conformance.py`;
- the ledger: `docs/facts/uncovered.json`, `pyeye.docs_facts.ledger.updated`, `DocEntry.covers`;
- the release stamp: `scripts/changelog.py` `prepare` (`FACT_LEDGERS`);
- the CI summary: the `Docs facts changed in this PR` step in `.github/workflows/ci.yml`.

**Verify:** GOLD. `uv run python scripts/docs_facts.py check` exits 0 on the branch. `uv run pytest tests/test_docs_facts_removed.py tests/test_docs_facts_ledger.py tests/test_changelog_tool.py tests/test_mcp_surface_conformance.py` passes. Together they cover the append-on-disappearance, each `match` mode, the "removed" marker, the sunset, history exemption, the ledger's baseline and `new` sections, the stamp and its no-op on an older checkout.
