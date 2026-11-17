---
date: "2026-11-17"
title: "Docs checks run over the doc registry and the live tool descriptions, with a per-page shrink-only allow-list (#825)"
issues: [825, 818]
anchors: ["pyeye.docs_facts.rules.RULES", "pyeye.docs_facts.rules.run", "pyeye.docs_facts.rules.ratchet", "pyeye.docs_facts.rules.RULE_IDS", "pyeye.docs_facts.docs.DocEntry", "pyeye.docs_facts.rules._removed_names", "tests/test_docs_facts_rules.py", "tests/test_docs_facts_skills.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-17 — Docs checks run over the doc registry and the live tool descriptions, with a per-page shrink-only allow-list (#825)

**Friction:** After #824 the facts had one source, but the ten point checks still each kept their own file list, the gap #818 found. Moving them showed the cost of those lists. The #417 ceiling check looked only at `expand` and `outline`, so `trace`'s description named the `members` and `subclasses` edges without the static-surface caveat, and CI stayed green. The env-var and server-command checks still globbed `docs/source/*.rst`. Three skills kept exact lists in hidden anchor comments, and the auditor kept hand copies of the taxonomy tables.

**Decision:**

- **Two kinds of check, both over `DOCS`.** A fact check binds a value in a fact block: the skills now bind `edges.implemented`, `review.*` and `duplication.*`, and their old anchors and copied tables are gone. A prose rule requires or forbids phrasing. It is a `Rule` in `RULES`, run by `docs_facts check` over every registered page of its kinds and over every live MCP tool description (core, admin and plugin), never over a list of its own. Fact-block content is skipped. The rules are `static-ceiling` (#417), `absence-prose` (#568), `edge-counts-prose` (#396), `env-name` (#556, #628) and `server-command` (#553). History pages are exempt (C1).
- **One ratchet.** `DocEntry.allow` maps a rule ID to the count of violating lines a page may still have. `ratchet` fails when a page has more, and also when it has fewer and the count wasn't lowered, so a fix lowers it in the same PR. A key outside `RULE_IDS` or a zero count fails. Tool descriptions have no allow-list. #826's `removed-name` rule uses the same field, agreed with #826 so there is one mechanism, not two.
- **Removed names pass only beside "removed"; never-existing names always fail.** `_removed_names()` is the one source of removed names. It is empty until #826 fills it from `docs/facts/removed.json`, and a live page may name one only on a line that says "removed" (C8 Q2). The wrong names the old checks caught (`PYEYE_PACKAGES`, `uv run pyeye`, `mcp dev` and the like) were never read or never worked. They were never removed, so they always fail, and "removed" beside one would be a false claim (D12).
- **Pins come from the snapshot.** The core and plugin tool-name pins read the committed `docs/facts/facts.json`, not hand-kept sets, so a rename shows in the PR's snapshot diff.
- **One unmeasured set.** `edges.inspect_unmeasured` is parsed (not imported) from the response linter's `_PHASE4_UNMEASURED_EDGES`, so the #396 rule and the live-response check can't diverge.
- **Rejected:** allow-lists kept in `rules.py` beside the rules. C8 says the counts live in the registry, and a second home would split them from the page they describe. Also rejected: scanning `operations/*.py` comments as docs. Internal contracts are checked by object (`resolve_members`, `resolve_subclasses`, `outline`), and the docs surface is the descriptions a model actually reads.

**Anchor:** `pyeye.docs_facts.rules.RULES` / `run` / `ratchet` / `RULE_IDS` / `_removed_names`; `pyeye.docs_facts.docs.DocEntry.allow`; `pyeye.docs_facts.extractors.review`; `pyeye.docs_facts.extractors.duplication`; `pyeye.docs_facts.extractors.edges.inspect_unmeasured`; design `docs/superpowers/specs/2026-11-17-docs-built-on-facts-design.md` (#822) §1, C1, C8; #825, #826, #818.
**Applies-to:**

- the rule table and its runner: `pyeye.docs_facts.rules.RULES`, `pyeye.docs_facts.rules.run`, called from `pyeye.docs_facts.cli.plan`;
- the ratchet: `pyeye.docs_facts.rules.ratchet`, `pyeye.docs_facts.rules.allow_problems`, `pyeye.docs_facts.docs.DocEntry.allow`;
- the removed-name source: `pyeye.docs_facts.rules._removed_names` (#826 fills it from `docs/facts/removed.json`);
- the skill bindings: `skills/python-explore/SKILL.md`, `skills/architecture-review/SKILL.md`, `skills/architecture-review/auditor.md`, `skills/duplication-review/SKILL.md`;
- the snapshot pins: `tests/test_mcp_surface_conformance.py::TestMcpSurface`, `tests/test_plugin_tool_names_conformance.py`.

**Verify:** PARTIAL. Gold: `uv run python scripts/docs_facts.py check` exits 0, and `uv run pytest tests/test_docs_facts_rules.py tests/test_docs_facts_skills.py tests/test_docs_facts_skill_extractors.py` passes. That covers each rule's historic misses and honest phrasings, the ratchet in both directions, an unknown rule key, and the skills' bindings. Also gold: `git grep -nE "glob\(|rglob\(" -- 'tests/test_docs_*' 'src/pyeye/docs_facts/rules.py'` finds no glob of doc files. Unverifiable: that every *future* docs check goes through `RULES` or a fact block. Only review enforces that.
