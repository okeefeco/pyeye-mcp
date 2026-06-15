# python-explore Skill Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the shipped `python-explore` skill around pyeye's progressive-disclosure API (resolve/inspect/outline/expand/trace) with the honest-limits rule centred, slim the internal `03-mcp-dogfooding.md` to defer tool mechanics to the skill, and add a mechanical anti-drift guard so the skill can't silently rot against the edge registry again.

**Architecture:** Three artifacts change — `skills/python-explore/SKILL.md` (full rewrite, ships to users), `.claude/instructions/03-mcp-dogfooding.md` (slim + defer, internal only), and a new dependency-free conformance test that pins the skill's documented edge set to `_IMPLEMENTED_EDGES`. The design of record is `docs/superpowers/specs/2026-06-15-python-explore-skill-rewrite-design.md` — read it before implementing; this plan pins the testable contracts and points at that spec for prose content.

**Tech Stack:** Markdown (skill + instructions), Python stdlib (`re`, `pathlib`) for the conformance test, pytest.

---

## Spec reference

Every prose decision (frontmatter triggers, section ordering, the honest-limits wording, the worked examples, what to keep/cut in `03`) lives in the spec. Read these spec sections before each task:

- Skill body: spec "Skill structure (rewritten `skills/python-explore/SKILL.md`)" — sections 1–10.
- `03` slim: spec "`03-mcp-dogfooding.md` (internal) — slimmed shape".
- Guard: spec "Anti-drift conformance guard".
- Verified ground truth (the facts the skill must state accurately) and "Out of scope".

**Verified facts the skill MUST state (do not re-derive — copied from the spec's verified ground truth):**

- Live primitives: `resolve`, `resolve_at`, `inspect`, `outline`, `expand`, `trace`.
- Live `expand`/`trace` edges (= `_IMPLEMENTED_EDGES`): `members`, `callees`, `imported_by`, `subclasses`, `superclasses`, `imports`, `enclosing_scope`.
- Deferred (= `_DEFERRED_REFERENCE_BACKEND_EDGES`, NOT available, #333): `callers`, `references`, `read_by`, `written_by`, `passed_by`, `overrides`, `overridden_by`, `decorated_by`, `decorates`.
- `resolve` success returns `{found, handle, kind, scope, location}` (location included); ambiguous returns `{found, ambiguous, candidates: [...]}`.
- `inspect.edge_counts` measures only: class → members+superclasses+subclasses; module → members; other kinds → empty. NOT callers/references.

---

## File Structure

- `tests/test_python_explore_skill_conformance.py` — NEW. Dependency-free pytest module. Parses the skill's machine-readable edge anchor and pins it to the registry; checks frontmatter name stability. Single responsibility: prevent skill/registry drift.
- `skills/python-explore/SKILL.md` — REWRITE. The shipped user-facing guide. Must satisfy the conformance test and encode spec sections 1–10.
- `.claude/instructions/03-mcp-dogfooding.md` — SLIM. Internal-only. Keep framing/metrics; delete the duplicated legacy tool catalogue; point to the skill.

---

## Task 1 — Add the anti-drift conformance test (failing first)

**Goal:** Encode the decision "the skill's documented supported-edge set is exactly the implemented registry, and the skill name is stable" as a test, so the skill rewrite has a mechanical target and future edge changes fail loudly. Written first (TDD) — it fails until Task 2 adds the anchor.

**Files:** `tests/test_python_explore_skill_conformance.py` (new).

**Interfaces consumed** (from `src/pyeye/mcp/operations/edges.py`, copy verbatim):

```python
from pyeye.mcp.operations.edges import (
    _IMPLEMENTED_EDGES,             # frozenset[str]
    _DEFERRED_REFERENCE_BACKEND_EDGES,  # frozenset[str]
)
```

**Interface produced** (the anchor contract Task 2 must satisfy): the skill file contains exactly one line matching `<!-- pyeye-supported-edges: <space-separated edge names> -->`, and the whitespace-split token set of that list equals `set(_IMPLEMENTED_EDGES)`.

**Tests:** This task *is* the tests. Pin these assertions (dependency-free — `re` + `pathlib` only; do NOT add a yaml dependency):

```python
import re
from pathlib import Path

from pyeye.mcp.operations.edges import (
    _IMPLEMENTED_EDGES,
    _DEFERRED_REFERENCE_BACKEND_EDGES,
)

SKILL = Path(__file__).resolve().parent.parent / "skills" / "python-explore" / "SKILL.md"
_ANCHOR = re.compile(r"<!--\s*pyeye-supported-edges:\s*(.*?)\s*-->")


def _skill_text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _documented_edges() -> set[str]:
    m = _ANCHOR.search(_skill_text())
    assert m is not None, (
        "SKILL.md must embed a `<!-- pyeye-supported-edges: ... -->` anchor "
        "listing the supported expand/trace edges"
    )
    return set(m.group(1).split())


def test_skill_file_exists() -> None:
    assert SKILL.is_file(), f"skill not found at {SKILL.as_posix()}"


def test_documented_edges_equal_implemented_registry() -> None:
    # Drift guard: the skill's supported-edge list must track edges.py exactly.
    assert _documented_edges() == set(_IMPLEMENTED_EDGES)


def test_no_deferred_edge_listed_as_supported() -> None:
    # The #1 bug class: never present a reference-backend edge as available.
    assert _documented_edges().isdisjoint(_DEFERRED_REFERENCE_BACKEND_EDGES)


def test_skill_name_is_stable() -> None:
    # The plugin resolves the skill by this name; a rename would unship it.
    assert re.search(r"^name:\s*python-explore\s*$", _skill_text(), re.MULTILINE)


def test_skill_declares_a_description() -> None:
    assert re.search(r"^description:\s*\S", _skill_text(), re.MULTILINE)
```

**Constraints:**

- Dependency-free: stdlib only. Do not import `yaml`.
- `_IMPLEMENTED_EDGES` / `_DEFERRED_REFERENCE_BACKEND_EDGES` are module-private (leading underscore) but are the genuine source of truth; importing them in a test in the same project is acceptable and intentional (the test's whole point is to bind to them).
- Path resolution must work when pytest is run from the repo root: `Path(__file__).resolve().parent.parent` is the repo root, then `skills/python-explore/SKILL.md`.

**Acceptance criteria:** `uv run pytest tests/test_python_explore_skill_conformance.py` runs and **fails** on the edge/anchor assertions (because the current skill has no anchor and still lists legacy tools) — confirming the test exercises the contract. `test_skill_file_exists` passes (the file exists today). Do NOT commit yet — commit with Task 2 (red+green together).

**Risks:** If the current skill happens to contain a coincidental `pyeye-supported-edges` string, the anchor test could behave unexpectedly — verify by reading the failing output; the current skill has no such anchor, so the anchor assertion should fail cleanly.

---

## Task 2 — Rewrite `skills/python-explore/SKILL.md`

**Goal:** Replace the rotted skill with the progressive-disclosure guide so users get correct, honest guidance. Makes Task 1's test pass and encodes spec sections 1–10.

**Files:** `skills/python-explore/SKILL.md` (full rewrite).

**Interface produced:** the `<!-- pyeye-supported-edges: members callees imported_by subclasses superclasses imports enclosing_scope -->` anchor (the exact 7 edges, space-separated), placed adjacent to the human-readable supported-edges table so the two are edited together.

**Content contract (from spec sections 1–10 — read the spec; key pinned decisions):**

- **Frontmatter:** keep `name: python-explore` unchanged. Broaden `description` to understanding **and** change, with triggers and the do-NOT-trigger exclusions per spec section "Frontmatter". State "Requires the pyeye MCP server."
- **Model + gates:** orient (`resolve` → `inspect`/`outline`) → drill (`expand`) → trace (`trace`); canonical handles are the currency. Two rigid gates (pyeye-before-blind-Read; don't re-explore in-context). Summary is softened to judgement (spec section 8), NOT a mandatory 4-field block.
- **Primitives table:** all six, accurate returns. `resolve` returns handle+kind+scope+**location** (answers "where?" without a second call); cover the **ambiguous → `candidates`** path. No source content anywhere — Read is the content layer.
- **Supported-edges table + anchor:** the 7 live edges with direction + meaning. Anchor matches exactly.
- **⭐ Honest-limits rule:** `callers`/`references` + the rest of the deferred set are NOT available (#333); pyeye refuses. Do NOT fake them with grep OR the deprecated `find_references`/`get_call_hierarchy`/legacy tools. State what you CAN answer (forward callees, imported_by, sub/superclasses, members, imports, enclosing_scope). Absence-vs-zero note for `edge_counts`.
- **Workflow flowchart** (dot) + **worked examples**: generic placeholders (`myapp.config.Settings`, `myapp.cache.Cache`) plus one stdlib scope demo (`inspect("pathlib.Path")` → `scope: external`; `expand("pathlib.Path", edge="subclasses")` → project-only). Include: inspect-a-class, ambiguity, `resolve_at` position→handle, outline-a-module, callees, imported_by, subclasses, a `trace` closure, and the **"who calls this → honest refusal"** case.
- **Failure mode:** pyeye unavailable → note, degrade to Read, warn. **Red flags:** per spec section 10, including "faking callers via grep/legacy tools".

**Constraints:**

- IMPORTANT: do not recommend `lookup`, `find_symbol`, `find_references`, `get_call_hierarchy`, `find_subclasses`, `analyze_dependencies`, `goto_definition`, `get_type_info` as tools to use. The legacy reference tools (`find_references`, `get_call_hierarchy`) appear ONLY inside the honest-limits warning as "don't use these to fake callers".
- Every edge named as supported must be in `_IMPLEMENTED_EDGES`; every deferred edge mentioned must be framed as NOT available.
- Markdown must pass the repo's `markdownlint` pre-commit hook (mirror the formatting conventions of the existing skill — fenced code blocks, table syntax, heading levels).
- `dot` graph: keep it valid Graphviz like the current skill's block.

**Acceptance criteria:**

- `uv run pytest tests/test_python_explore_skill_conformance.py` passes (all five tests).
- Manual read-through confirms: no legacy tool recommended; honest-limits section present and prominent; examples localised; `resolve` location + ambiguity covered; `resolve_at` demonstrated.
- Commit Task 1's test together with this rewrite (red+green in one commit), message scoped to the skill rewrite and `#374`.

**Risks:** Over-trimming useful guidance — preserve the genuinely valuable behavioural gates and the failure-mode/red-flags framing from the original. Under-stating the honesty rule — it is the headline; give it visual prominence (its own `##` section, not a bullet).

---

## Task 3 — Slim `.claude/instructions/03-mcp-dogfooding.md`

**Goal:** Remove the duplicated, stale legacy tool catalogue so there's one source of truth (the skill) and the repo dogfoods its own shipped skill. Internal-only file; lower risk but in scope per the issue's "no parallel copy that can drift".

**Files:** `.claude/instructions/03-mcp-dogfooding.md`.

**Content contract (spec "`03-mcp-dogfooding.md` (internal) — slimmed shape"):**

- **Keep:** "we build pyeye — we MUST use it" framing; semantic-over-text principle; the existing redesign "preferred operations" note (resolve/inspect/outline/expand/trace are the surface; legacy tools deprecated, backwards-compat only) — it already points at `docs/api-redesign.md`, which is confirmed present and current; metrics commands (`mcp-report`, `mcp-logs`, etc.) and a high-level "measuring success" note; repo-specific dogfooding context.
- **Replace:** the entire "Pattern Replacements" legacy catalogue and the legacy "Required Workflow for Python Code Analysis" phases (`find_symbol`/`goto_definition`/`get_call_hierarchy`/`find_references`/…) and the legacy worked examples that call them, with a short pointer block: **"For tool mechanics — which primitive to call, the supported edges, and the honest-limits rule — the `python-explore` skill is the single canonical reference. Don't restate tool usage here."**

**Constraints:**

- Do not delete the dogfooding philosophy or metrics sections — only the duplicated tool mechanics.
- Keep the file's numbered-instruction-file conventions and heading style; it's loaded via `CLAUDE.md`.
- Must pass `markdownlint`.

**Acceptance criteria:** `03-mcp-dogfooding.md` no longer presents legacy tools as the workflow; contains the deferral pointer to the skill; framing/metrics retained. Commit scoped to the `03` slim and `#374`.

**Risks:** Accidentally removing the "preferred operations" redesign note (it's the bridge to the new API) — keep it.

---

## Task 4 — Full validation and finalise

**Goal:** Confirm nothing regressed and all gates pass before the work is declared done.

**Files:** none (verification only).

**Steps / acceptance criteria:**

- `uv run pytest` — full suite green, including the new conformance test. (Per repo convention, run the whole suite, not just the new file.)
- Pre-commit hooks pass on all touched files (markdownlint in particular) — already exercised by the Task 2/3 commits; re-confirm with `uv run pre-commit run --files skills/python-explore/SKILL.md .claude/instructions/03-mcp-dogfooding.md tests/test_python_explore_skill_conformance.py` if any doubt.
- Frontmatter sanity: `name: python-explore` unchanged, `description` present and non-empty (covered by conformance tests).
- `git status` clean (all intended files committed; nothing stray) — verify per `feedback_dispatch_git_verify`.

**Risks:** A full-suite run surfaces an unrelated pre-existing failure — if so, confirm it reproduces on the base commit before attributing it to this work; do not mark complete with a genuinely new failure.

---

## Notes for execution

- Work happens in the existing worktree `.claude/worktrees/docs/374-rewrite-python-explore-skill` on branch `docs/374-rewrite-python-explore-skill`. Env already synced (`uv sync --all-extras`).
- This is a docs-mostly change; the one Python file is the conformance test. The repo's 85%-coverage gate is not the relevant bar here — markdownlint + the conformance test are.
- PR body should reference `Closes #374` and mention follow-up `#377` (stale `inspect.py` docstrings).
