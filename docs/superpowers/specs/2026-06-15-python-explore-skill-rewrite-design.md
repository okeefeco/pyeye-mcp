# Rewrite the `python-explore` skill around the progressive-disclosure API

**Issue:** #374
**Date:** 2026-06-15
**Status:** Design
**Audience of the artifact:** end users of the `pyeye` Claude Code plugin (the skill ships to them)

## Problem

`skills/python-explore/SKILL.md` is a **shipped, user-facing** skill — the `pyeye`
plugin's marketplace entry (`.claude-plugin/marketplace.json`) has `source: "./"`,
so Claude Code bundles the repo's top-level `skills/` with the plugin. It is how
every pyeye user learns to drive the tool, and its guidance is now a **shipped
correctness bug**:

1. It centres `lookup()` as the "primary entry point" — a superseded transitional
   surface. It never mentions the live primitives `resolve` / `resolve_at` /
   `inspect` / `outline` / `expand` / `trace`.
2. Its toolkit is the **deprecated legacy API** (`find_symbol`, `find_references`,
   `get_call_hierarchy`, `find_subclasses`, `analyze_dependencies`, `list_*`),
   presented with no deprecation note.
3. **Most serious:** it recommends `find_references` / `get_call_hierarchy` to answer
   "who calls this" / "what references this", framed as *more reliable than grep*.
   The redesign's central finding (#332/#333) is that Jedi's reverse-reference search
   under-reports non-deterministically — which is exactly why `callers` / `references`
   are **deferred** (gated on the Pyright backend, #333) and the new surface *refuses*
   rather than returning wrong/empty data. The skill inverts the honesty invariant the
   whole API is built on, and ships that to users.
4. It is coordinate/`full_name`-centric, not canonical-handle-centric.
5. Every example uses a foreign `aac.logical.patterns.common.cdis...` path users can't
   relate to.

The internal counterpart `.claude/instructions/03-mcp-dogfooding.md` (imported by this
repo's `CLAUDE.md`; governs Claude when working *on* pyeye, never shipped) restates the
same stale tool mechanics — the duplication is *why* the two drifted.

## Goal

Rebuild the skill as the **canonical user-facing "how to explore Python with pyeye"
guide**, structured around the API's own model — orient cheap, drill on demand, trace
across hops — with the **honest-limits rule front and centre**. Slim
`03-mcp-dogfooding.md` to keep only its internal framing and **defer all tool mechanics
to the skill**, so there is one source of truth and the repo literally dogfoods its own
shipped skill.

## Verified ground truth (as of 2026-06-15)

Do not trust prose docs here over the source — these were verified against the live MCP
tool list and `src/pyeye/mcp/operations/`:

- **Live primitives (on the wire):** `resolve`, `resolve_at`, `inspect`, `outline`,
  `expand`, `trace`.
- **Live `expand` / `trace` edges** (`_IMPLEMENTED_EDGES` in
  `src/pyeye/mcp/operations/edges.py`): `members`, `callees`, `imported_by`,
  `subclasses`, `superclasses`, `imports`, `enclosing_scope`. The static edge set is
  **complete**; `not_yet_implemented` is empty.
- **Deferred until the Pyright reference backend (#333)** —
  `_DEFERRED_REFERENCE_BACKEND_EDGES`: `callers`, `references`, `read_by`,
  `written_by`, `passed_by`, `overrides`, `overridden_by`, `decorated_by`, `decorates`.
- **`inspect.edge_counts` actually measures** (`_build_edge_counts` in
  `inspect.py`): `class` → `members` + `superclasses` + `subclasses`;
  `module` → `members`; function / method / attribute / property / variable → **empty**
  (their only edges were the deferred reference ones). It does **NOT** measure
  `callers` / `references`. (Note: some `inspect.py` *docstrings* still claim it
  measures `callers`/`references` — those are stale; the implementation is the source of
  truth. Filed as follow-up issue #377; out of scope for this PR.)
- **`resolve` success returns** `{found, handle, kind, scope, location}` — handle +
  kind + `project`/`external` scope **and a `location` pointer** (verified against
  `_SuccessResult`, `src/pyeye/mcp/operations/resolve.py:92`). So resolve already answers
  "where is this defined?" — you do **not** need a follow-up `inspect` just for location;
  `inspect` adds signature / docstring / `edge_counts`. (Note: resolve.py's own docstring
  example omits `location`; the TypedDict is the source of truth.)
- **`resolve` can return an ambiguous result.** `_AmbiguousResult`
  (`resolve.py:100`) is `{found: true, ambiguous: true, candidates: [...]}`, each
  candidate `{handle, kind, scope, location}`. A bare name (`"Config"`) matching several
  symbols commonly returns this — the agent picks from `candidates` or re-resolves with
  the full dotted handle.
- **No source content** in any response — pyeye returns pointers (`file`,
  `line_start`, `line_end`) + structured facts; `Read` is the content layer.

## Design decisions (settled at brainstorm)

1. **Framing — understand + change.** Broaden from the current modify-only framing to
   "understand any Python code with pyeye"; pure-comprehension Q&A ("how does X work")
   is first-class, with change being one outcome.
2. **Gates.** Keep two rigid behavioural gates — *pyeye before a blind `Read()` on
   unfamiliar Python*, and *never re-explore what's already in context*. **Soften** the
   mandatory 4-field summary to a judgement call ("state your mental model when it helps
   the user"), reducing ceremony on pure-understanding queries.
3. **Examples.** Generic placeholder handles (`myapp.config.Settings`,
   `myapp.cache.Cache`) for the main walkthrough (project-scope realism), **plus one
   stdlib** target (`inspect("pathlib.Path")`) to illustrate the project/external scope
   distinction.
4. **`03-mcp-dogfooding.md`.** Full slim + defer: keep internal framing only
   (we-build-this-so-we-dogfood-it, semantic-over-text, the redesign "preferred
   operations" note, metrics commands, a high-level "measuring success" note); delete
   the duplicated legacy pattern-replacement catalogue and legacy workflow phases;
   point to `python-explore` as the single canonical tool-mechanics reference.

## Skill structure (rewritten `skills/python-explore/SKILL.md`)

### Frontmatter

`description` broadened to understanding + change:

- **Triggers on:** "how does X work", "what does", "why is X doing", "trace", "add
  feature", "implement", "refactor", "debug", "extend", **and** relationship questions
  ("what does this call", "what imports this", "what subclasses this").
- **Does NOT trigger for:** explicit "show me / print / read this file", "what's the
  syntax for" (language question), single-line typo/string fix with exact location
  given, adding a new test case only, or when pyeye output for the symbol is already in
  conversation context.
- States "Requires the pyeye MCP server."

### Body sections

1. **One-liner + the model.** *Build a structural model with pyeye before reading or
   changing Python — orient cheap, drill on demand.* Progressive disclosure as the
   spine: **orient** (`resolve` → `inspect` / `outline`) → **drill** (`expand`) →
   **trace across hops** (`trace`). **Canonical handles** (`a.b.c.Name`, definition-site,
   stable across edits, dedup across import aliases) are the currency — everything
   downstream takes a handle.

2. **Skill type — mixed rigid/flexible.**
   - Rigid gates: (1) first move on unfamiliar Python is pyeye, not a blind `Read()`;
     (2) never re-explore what's already in context.
   - Flexible: depth scaling, which calls to make, and stating your mental model when it
     aids the user (softened from the old mandatory summary).

3. **Do NOT trigger when** — the exclusion list from the frontmatter, restated for the
   agent with the "already in context → skip to using it" shortcut.

4. **The primitives (the toolkit).** Table of `resolve` / `resolve_at` / `inspect` /
   `outline` / `expand` / `trace` with one-line purpose, accurate return summary, and the
   cheap→rich ordering. Emphasise: `resolve` returns `handle` + `kind` + `scope` +
   `location` (so it answers "where?" without a second call); no source content anywhere
   — `Read` with the returned `file:line` pointers when you need the actual code.
   - **Resolving ambiguity.** A bare name can match several symbols — `resolve` then
     returns `{ambiguous: true, candidates: [...]}`. The agent picks the right candidate
     (each has `handle` / `kind` / `scope` / `location`) or re-resolves with the full
     dotted handle. This replaces the old skill's "use the full dotted path" advice with
     the canonical-handle version.

5. **Supported edges.** Table of the seven live `expand`/`trace` edges with
   direction + meaning: `members`, `callees`, `imported_by`, `subclasses`,
   `superclasses`, `imports`, `enclosing_scope`.

6. **⭐ The honest-limits rule (the #1 fix).** Prominent section:
   - `callers` / `references` (and `read_by` / `written_by` / `passed_by` / `overrides`
     / `overridden_by` / `decorated_by` / `decorates`) are **NOT available** — deferred
     to the Pyright reference backend (#333). pyeye **refuses** rather than returning
     wrong/empty data.
   - **Do NOT fake "who calls this" / "what references this"** with `grep` **or** the
     deprecated legacy tools (`find_references`, `get_call_hierarchy`). They
     under-report non-deterministically — the exact failure the new API exists to avoid.
     Say *"reverse-reference data isn't reliably available yet"* and offer what you can
     answer instead.
   - **What you CAN answer reliably:** forward `callees`, `imported_by`,
     `subclasses` / `superclasses`, `members`, `imports`, `enclosing_scope`.
   - **Absence vs zero:** a missing `edge_counts` key means *not measured*, not zero —
     don't read absence as "none."

7. **Workflow flowchart + worked examples.**
   - Updated `dot` flowchart: trigger → (explicit read? → `Read`) → (already in context?
     → use it) → orient → drill / trace as needed → act.
   - Examples use generic placeholders **plus one stdlib** scope example. Coverage:
     - "What is this class?" → `resolve` → `inspect` (kind, location, `edge_counts`).
     - **Ambiguity** → `resolve("Settings")` returns `{ambiguous: true, candidates}`;
       pick the candidate (or re-resolve with the full handle), then continue.
     - **Position → handle** → `resolve_at(file, line, column)` for "I'm looking at this
       line / stack-trace frame — what is it?" (the coordinate-first intake path).
     - "What's inside this module?" → `outline`.
     - "What does this function call?" → `expand(edge="callees")`.
     - "Who imports this module?" → `expand(edge="imported_by")`.
     - "What subclasses this base?" → `expand(edge="subclasses")`.
     - A multi-hop closure → `trace(follow=[...])`.
     - **"Who calls this function?" → the honest refusal** (state the limitation, do NOT
       grep or use legacy tools, offer `callees`/forward alternatives).
     - **Scope demo** → `inspect("pathlib.Path")` returns `scope: "external"`;
       `expand("pathlib.Path", edge="subclasses")` returns project-internal classes only.

8. **Mental model (softened summary).** When it aids the user, state the symbol's
   location, dependencies, and likely impact using **canonical handles + `file:line`**
   (stable references, per `feedback_stable_references`). Not mandatory ceremony; scale
   to the task.

9. **Failure mode.** pyeye unavailable → note it explicitly, degrade to `Read()`, warn
   that static analysis is off. Don't block.

10. **Red flags.** First call is `Read()` on unexplored Python; grep to find a
    definition **or** a relationship; reaching for deprecated `find_*` / `get_*` tools;
    **faking `callers` via grep/legacy tools**; re-exploring what's already in context.

## `03-mcp-dogfooding.md` (internal) — slimmed shape

Keep:

- "We build pyeye — we MUST use it" framing and the semantic-over-text principle.
- The redesign "preferred operations" note (resolve/inspect/outline/expand/trace are the
  surface; legacy tools deprecated, backwards-compat only).
- Metrics commands (`mcp-report`, `mcp-logs`, etc.) and a high-level "measuring success"
  note.
- Repo-specific dogfooding context (we develop *in* this codebase).

Replace / remove — **all** sections that recommend legacy tools or the reverse-reference
search, not just the obvious catalogue. The rot is spread across at least six sections
(verified against `main`): "Required Workflow for Python Code Analysis", "Pattern
Replacements (MANDATORY)", "Real-World Usage Examples", "Troubleshooting Common
Scenarios", "Measuring Success", and "Performance Tips". The Troubleshooting metric
(*"Always start with `find_references` — NEVER skip this"*) and the Measuring-Success
metrics (*"100% of refactoring should use `find_references` first"*, *"All inheritance
checks should use `find_subclasses`"*) are the **same honesty bug as #374, sitting
internally** — they steer the agent to the exact unreliable reverse-reference search the
redesign rejects, so they must go too. Replace the removed mechanics with a short
pointer: **"For tool mechanics — which primitive to call, the supported edges, and the
honest-limits rule — the `python-explore` skill is the single canonical reference. Don't
restate tool usage here."** After the sweep, no legacy tool (`find_references`,
`find_subclasses`, `get_call_hierarchy`, `find_symbol`, `goto_definition`,
`get_type_info`, `lookup`) should remain as a *recommendation* — a bare mention inside a
"these are deprecated, use the skill" note is the only acceptable residue.

## Anti-drift conformance guard

`03` happened because the skill drifted from the edge registry; "the skill is the single
source of truth" is an organisational defence only. Add a **mechanical** guard so the
next edge change can't silently re-rot the skill:

- The skill embeds a machine-readable anchor — an HTML comment listing the edges it
  documents as supported, e.g.
  `<!-- pyeye-supported-edges: members callees imported_by subclasses superclasses imports enclosing_scope -->`
  (kept adjacent to the human-readable supported-edges table so they're edited together).
- A small test (`tests/test_python_explore_skill_conformance.py`) parses that anchor and
  asserts the documented set **equals** `_IMPLEMENTED_EDGES` from
  `src/pyeye/mcp/operations/edges.py`, and asserts the skill names **no**
  `_DEFERRED_REFERENCE_BACKEND_EDGES` member as supported/recommended. If the registry
  changes, this test fails until the skill is updated — converting drift from a silent
  rot into a CI failure.
- The test also adds a **prose negative assertion**: the pure-legacy tools `lookup`,
  `find_symbol`, `goto_definition`, `get_type_info` must appear **nowhere** in the skill
  (they have no legitimate place in the rewrite). `find_references` /
  `get_call_hierarchy` are deliberately excluded from this ban — they legitimately appear
  inside the honest-limits "do NOT use these to fake callers" warning, so a blanket ban
  would false-positive. This catches a future "use `find_symbol`" sentence the edge
  anchor alone would miss; manual review remains the backstop for contextual cases.

This is the one piece of Python in an otherwise docs-only change; it exists specifically
to prevent a recurrence of the bug this issue fixes.

## Out of scope

- Any change to the pyeye Python implementation or the MCP tools themselves (the
  conformance test above only *reads* the registry; it does not change behaviour).
- Fixing the stale `callers`/`references` docstrings inside `inspect.py` — **filed as
  #377**.
- The `decision-log` skill.
- Retiring the legacy tools (tracked elsewhere; the skill just stops recommending them).

## Testing posture

This is a docs-mostly change: the repo's "all code changes need tests / 85% coverage"
gates don't meaningfully apply to the markdown. The relevant gates are **markdownlint**
(pre-commit) and the **conformance guard** test above. Run the full suite
(`uv run pytest`) before pushing anyway, per repo convention, to confirm the new test
passes and nothing else regressed.

## Acceptance

- Skill rewritten around `resolve` / `resolve_at` / `inspect` / `outline` / `expand` /
  `trace`; no recommendation of deprecated tools or the unreliable reverse-reference
  search; explicit "callers/references unavailable (#333) — don't fake them" guidance;
  canonical-handle-centric; examples localised (generic placeholders + one stdlib scope
  demo).
- `03-mcp-dogfooding.md` defers tool mechanics to the skill (no parallel copy that can
  drift).
- Skill description/triggers updated; the skill loads and triggers correctly.
- `resolve` guidance is accurate: success returns `location`; the ambiguous-result path
  (`candidates`) is covered with an example.
- `resolve_at` (position → handle) is demonstrated, not just listed.
- Every supported-edge and deferred-edge claim in the skill matches
  `src/pyeye/mcp/operations/edges.py` — enforced mechanically by the conformance test.
