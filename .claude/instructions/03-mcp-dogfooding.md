<!--
Audience: Claude Code
Purpose: Enforce MCP-first development workflow for Python code analysis
When to update: When the dogfooding stance changes. Tool MECHANICS (which
primitive, which edges, the honest-limits rule) live in the python-explore
skill — update there, not here, so the two never drift (the bug that
prompted #374).
-->

# MCP-First Development Workflow (Dogfooding Our Own Tools)

**CRITICAL**: We build PyEye — we MUST use it for our own development!

We're developing a powerful semantic code analysis tool. Falling back to raw
grep/glob for Python is like building a sports car and pushing it. ALL Python
work in this project MUST prioritise pyeye's semantic operations over text search.

## Core Principle: Semantic Over Text

**Always choose semantic understanding over text matching:**

- Understand code structure, not just text patterns.
- Navigate by meaning (canonical handles), not by string search.
- Leverage type information and relationships.

## The Tool Surface (redesigned API)

For Python code analysis, use the progressive-disclosure operations:
`resolve` / `resolve_at` / `inspect` / `outline` / `expand` / `trace`. They are
cheap by default (small structural responses, no source content), honour the
absence-vs-zero invariant, and operate on canonical handles that collapse
re-exported paths to the definition site.

The old Jedi-shaped tools (`find_symbol`, `goto_definition`, `get_type_info`,
`find_imports`, `find_subclasses`, `list_packages`, `list_modules`,
`get_module_info`, `list_project_structure`) have been **removed** from the MCP
surface — they are gone, not just discouraged.

**Nothing legacy survives.** The last three — `find_references`,
`get_call_hierarchy`, `analyze_dependencies` — were removed in v2.0 (#505), along
with the superseded `lookup` entry point. They were removed rather than left
deprecated because they answered *confidently and wrongly*: `get_call_hierarchy`
could never populate `callees` at all and anchored bare names on the first match
with no ambiguity signal; `analyze_dependencies` classified every first-party
module as third-party on a `src/` layout, which in turn silently disabled its own
cycle detection; `find_references` advertised "ALL usages" with no way to
distinguish an empty result from a failed search. Never use the
reverse-reference tools to answer "who calls / references this" — they no longer
exist, and the honest-limits rule in the skill is the whole answer. See
`docs/api-redesign.md` for the redesign background.

## Tool mechanics live in the `python-explore` skill

**Single source of truth.** Which primitive to call, the supported edges, the
honest-limits rule (callers/references are deferred to the Pyright backend, #333
— don't fake them), the worked examples — all of that lives in the
`python-explore` skill (`skills/python-explore/SKILL.md`), which ships to users.

Do **not** restate tool usage here. When you need the mechanics, use the skill —
this is the repo dogfooding its own shipped guide, and keeping one copy is what
stops the guidance from rotting (the failure that prompted #374). The skill's
supported-edge list is conformance-tested against the live edge registry
(`tests/test_python_explore_skill_conformance.py`).

## Measuring Success

We track pyeye adoption vs traditional search to make sure we actually drive the
car we build. The signal is simple: **Python navigation, discovery, and
relationship questions go through pyeye, not grep.** Adoption metrics are
surfaced by the `mcp-report` / `mcp-logs` commands documented in the root
`CLAUDE.md` ("Dogfooding Metrics Tracking").

Remember: **We build this tool — we must be its best users!**
