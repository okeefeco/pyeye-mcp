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

We're developing a semantic code analysis tool, and its job is to turn text into
facts. Use each tool for what it does best (#1130).

## Core Principle: Find with Text, Prove with Semantics

- **Discovery** of a concept or text ("is there a helper for X?", an error message,
  a config key): grep MAY find it. Then turn each hit into a canonical handle with
  `resolve_at` before relying on it.
- **Names you know:** `resolve`, NEVER grep.
- **Facts** (kind, signature, members, callees, imports, inheritance): ALWAYS from
  pyeye (`inspect` / `outline` / `expand` / `trace`), never from a grep hit's text.
- **Callers and references:** NEVER grep. pyeye defers them (#333); use the LSP,
  or say plainly that they aren't available.

## The Tool Surface (redesigned API)

For Python code analysis, use the progressive-disclosure operations:
`resolve` / `resolve_at` / `inspect` / `outline` / `expand` / `trace`. They are
cheap by default (small structural responses, no source content), honour the
absence-vs-zero invariant, and operate on canonical handles that collapse
re-exported paths to the definition site.

The v1 Jedi-shaped tools and the v2.0 legacy tools have been **removed** from the
MCP surface. NEVER reach for a tool name you remember from before v2.0. The
`python-explore` skill ("No legacy escape hatch") says which were removed
and why; `docs/api-redesign.md` has the redesign background.

## Tool mechanics live in the `python-explore` skill

**Single source of truth.** Which primitive to call, the supported edges, the
honest-limits rule (callers/references are deferred to the Pyright backend, #333
— don't fake them), the worked examples — all of that lives in the
`python-explore` skill (`.claude/skills/python-explore/SKILL.md`), which ships to users.

Do **not** restate tool usage here. When you need the mechanics, use the skill —
this is the repo dogfooding its own shipped guide, and keeping one copy is what
stops the guidance from rotting (the failure that prompted #374). The skill's
supported-edge list is the `edges.implemented` fact block: `docs_facts generate`
writes it from the live edge registry and `docs_facts check` verifies it.
`tests/test_docs_facts_skills.py` checks that the skill still binds it and that
its edge table explains every edge.

## Measuring Success

We don't count adoption any more (#1139). Dogfooding is checked by
verifying pyeye on real codebases: the `pyeye-verify` skill runs a
`pyeye-scenarios` scenario's probes, diffs them against its baseline and
scores how well pyeye serves an agent.

Remember: **We build this tool — we must be its best users!**
