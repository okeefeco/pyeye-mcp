---
date: "2026-06-21"
title: "`expand(subclasses)` stubs are AST-built pointers (no Jedi re-derivation, no signature)"
issues: [445, 419, 397, 333]
anchors: ["resolve_subclasses", "ClassSentinel", "pyeye.mcp.operations.edges", "pyeye._module_sentinel"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-21 — `expand(subclasses)` stubs are AST-built pointers (no Jedi re-derivation, no signature)

**Friction:** `resolve_subclasses` discarded the deterministic AST FQN `find_subclasses` already returns and re-derived a Jedi `Name` per subclass (`get_script` → `get_names` → `full_name` match), dropping any subclass whose `Name` it couldn't rebuild. Jedi's `full_name` is warm-inference-state-dependent (jedi #1796), so under artifact-cache thrash on Django (~2921 files) `expand(subclasses)` under-reported `find_subclasses`'s deterministic 1841 by 44–57% and drifted across result-cache rebuilds (1027 → 773 → 790) — re-importing the exact non-determinism #419 removed one layer down (#445).
**Decision:** Build each subclass adjacent as a `ClassSentinel` straight from the AST facts (`full_name` + file + `line`/`end_line`), never re-deriving a Jedi `Name` and never dropping. A subclass stub is a **pointer** (handle + location + kind) — the constructor signature is an `inspect` drill detail, not a one-hop `expand` field — symmetric with `imported_by`'s `ModuleSentinel`. The sentinel exposes `.type`/`.full_name` so it round-trips as a resolver INPUT at hop 2+ of `trace(follow=["subclasses"])`. Rejected: keep the Jedi `Name` when it resolves and fall back to a sentinel only on failure — that yields a deterministic *set* with non-deterministic *content* (signature flickers in/out across rebuilds), a subtler version of the same trust violation. Also rejected: re-add `signature` from the AST. A *faithful* signature needs an MRO walk — a subclass usually inherits its constructor (`inspect`/`members` already report the inherited `__init__` via Jedi, e.g. `DjangoPlugin(project_path: str)` though `DjangoPlugin` defines none), so the multi-file inference whose non-determinism #445 removed would come straight back; a *cheap* own-file-only signature is worse, present-but-wrong (`DjangoPlugin()`). Pointer-only is the honest stable contract, stated explicitly in the `stubs.py` docstring and the `python-explore` skill. `find_subclasses` now also carries `end_line` (`ClassDef.end_lineno`) and `get_end_line` honours an explicit `.end_line`, so the class span survives without Jedi.
**Anchor:** `resolve_subclasses` + `ClassSentinel` (`pyeye.mcp.operations.edges` / `pyeye._module_sentinel`); #445 (refs #419, #397, #333).
**Verify:** gold — `tests/unit/mcp/operations/test_subclasses_no_silent_drop.py`: with `find_subclasses` stubbed to a fixed set and `file_artifact_cache.get_script` patched to raise, `resolve_subclasses` returns all 3 handles (old code returned `[]`); `expand("pkg.base.Animal","subclasses")` equals the `find_subclasses` set and is identical across `invalidate_all()`; `trace(["subclasses"], max_depth=2)` reaches grandchild `pkg.middle.Dog` (sentinel round-trips as resolver input).
