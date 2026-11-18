---
date: "2026-11-18"
title: "Documented tool examples are executed against a fixture and matched on structure, with every trim marked (#828)"
issues: [828, 818, 843]
anchors: ["pyeye.docs_facts.examples.parse_examples", "pyeye.docs_facts.examples.match_shown", "pyeye.docs_facts.examples.allows_examples", "pyeye.docs_facts.binding.fences", "tests/test_docs_examples.py", "tests/fixtures/docs_examples"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-18-828-runnable-examples-may-live-on-any-prose-page-for-humans.md"]
superseded_by: []
---

## 2026-11-18 — Documented tool examples are executed against a fixture and matched on structure, with every trim marked (#828)

**Friction:** #818's sweep found tool examples that no longer matched the tools. `docs/api/pydantic-tools.md` showed `base_class` and `config_class` keys that `find_pydantic_models` doesn't return, and the skill's worked examples were pseudo-calls nobody ran. An example is a claim about a response, and nothing checked it. Building the runner also showed that `resolve_at` resolves a relative `file` against the server's working directory, not `project_path` (filed as #843).

**Decision:**

- **Tag grammar.** A fenced block with info `json pyeye-example tool=<tool> [fixture=<name>]` is a runnable example. Its body is the call's arguments as a JSON object, never including `project_path`. An optional `json pyeye-output` block straight after it (blank lines only in between) is its shown output.
  - The grammar is strict. An info string mentioning `pyeye-` that doesn't parse, an unknown or repeated key, a missing `tool=`, a stray output block, a second output or a body that isn't JSON is a `check` problem, never prose.
  - Fences are found with `binding.fences` (container-aware CommonMark, #838), so markers and examples share one scanner.
- **Where examples live.** Only in `DOCS` entries under `docs/api/` and `docs/reference/`, and in skills (`allows_examples`). A runnable example anywhere else fails `check`. The runner selects examples from `DOCS` only.
- **Execution.** `tests/test_docs_examples.py` calls each example through the real MCP server: the module server for core tools, and a server registered like `initialize_plugins` for plugin tools.
  - It runs against a copy of `tests/fixtures/<fixture>` (default `docs_examples`, a `myapp` package matching the skills' placeholder), with cwd set to that copy. The copy keeps sibling auto-discovery away from the other fixtures.
  - A primitive's response must pass `tests/conformance/response_linter.lint_response`.
  - A guard fails if fewer than 8 examples run.
- **Structure match (C10, maintainer ruling).**
  - Shown keys must exist in the response with the same JSON kind, recursively.
  - A level that leaves keys out carries `"…": "<omitted>"`, and a level that carries it must leave something out ("a trim signal must be true").
  - A trimmed array ends with `"<omitted>"`; more items than the response, or a needless `"<omitted>"`, fail.
  - `"k": "<absent>"` asserts `k` is not in the response, so absence-vs-zero claims (#568) stay checkable.
  - Values are ignored except `found`, `kind`, `reason` and `ambiguous`, which must be equal.
- **Rejected:**
  - Exhaustive output, which makes examples long and breaks every one whenever a response key is added.
  - Unmarked omission, which lets a trimmed example read as the whole response (D12).
  - Value matching, which is defeated by paths and line numbers.
  - Executing untagged examples, which are prose (§4).

**Anchor:** `pyeye.docs_facts.examples.parse_examples` / `match_shown` / `allows_examples`; `pyeye.docs_facts.binding.fences`; `pyeye.docs_facts.cli.plan` (reports the problems); `tests/test_docs_examples.py`; `tests/fixtures/docs_examples/`; design §4, D10 and C10 (`docs/superpowers/specs/2026-11-17-docs-built-on-facts-design.md`); #828, #818, #843.
**Applies-to:**

- the grammar and pairing: `pyeye.docs_facts.examples.parse_examples`, `pyeye.docs_facts.examples.allows_examples`;
- the match: `pyeye.docs_facts.examples.match_shown`;
- the gate: `pyeye.docs_facts.cli.plan` (`check`), `tests/test_docs_examples.py`;
- every tagged block in `skills/python-explore/SKILL.md` and `docs/api/pydantic-tools.md`, and any added later in `docs/api/`, `docs/reference/` or a skill.

**Verify:** gold. `uv run pytest tests/test_docs_examples.py tests/test_docs_facts_examples.py` passes, covering:

- every tagged example runs, lints and matches;
- each grammar problem;
- the pairing rules;
- the allowed places;
- every C10 rule in both directions.

`uv run python scripts/docs_facts.py check` exits 0.
