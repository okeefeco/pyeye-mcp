---
date: "2026-11-20"
title: "A result whose file resolves into a restricted directory is refused, at the resolver and at expand's adjacents (#999)"
issues: [999, 998, 993, 856, 909, 939, 626]
anchors: ["pyeye.resolver.resolve_handle", "pyeye.resolver.in_restricted_dir", "pyeye.mcp.operations.expand._without_restricted", "tests/test_restricted_symlink_results.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-20 — A result whose file resolves into a restricted directory is refused, at the resolver and at expand's adjacents (#999)

**Friction:** found by the #998 security re-review of #993. Jedi follows symlinks while it looks up an import. A symlink inside the project (`proj/etcmod2 -> /etc/python3.12`), or inside the project venv's `site-packages` (#993 adds that place), was followed, and pyeye returned the target: `resolve`/`inspect` found it, and `expand(imports)`/`trace` emitted it as a stub or node. The input checks (#856, #909, #939) and the pruned walks never see this route. No code runs, but a repository could expose a restricted file's symbols and docstrings. Verified live against the real `/etc/python3.12/sitecustomize.py`.

**Decision:** the maintainer approved the design (via coordinator-3, 2026-11-20).

- **One test, reused:** a result is refused when its Jedi name's file, RESOLVED (`path_utils.normalize_path`), is inside a restricted directory or a credential store, by `validation.restricted_dir`, the walkers' own prune test. That's `resolver.in_restricted_dir`. No new rule; a name with no file is never refused.
- **Choke point 1, `resolver.resolve_handle`:**
  - every canonical answer goes through it: `resolve`, `resolve_at`, `inspect`, `outline`, `expand`'s and `trace`'s sources and interior nodes, and plugin handle enrichment;
  - a refused anchor is `NotFound("unresolved")` with `RESTRICTED_DETAIL` and an internal `restricted` flag;
  - the operations show that detail as it is, instead of their "check the spelling" default, and skip the #993 environment note after it;
  - for a bare name, the policy's rules run first, so a legitimate same-named project symbol still wins; only when none answers is the refusal returned.
- **Choke point 2, `expand._without_restricted`** (in `expand_resolved`, before the cap and the stub builds; `trace` walks through it too): a refused adjacent is removed and REPORTED in the edge's existing loss field, never dropped silently. `imports` lists it in `unresolved_imports`, `superclasses` in `unresolved_superclasses`, and `callees` counts it in `unresolved_call_sites`. The other edges read the source's own file or the pruned project walks, so they can't reach one. If one ever did, it's dropped with a logged warning, since those edges have no loss field to report in.
- **No new keys or reasons.** The closed not-found reason sets (#626) are unchanged; the honest reason is in `detail`.
- **Kept, by test:** symlinks into any other directory (project and venv), and a symlinked project root.
- **Rejected:**
  - checking each tool separately, which would mean seven places to forget;
  - post-filtering only the final responses, which would leave `trace`'s walk and plugin enrichment reading the file;
  - a new `restricted` reason or response key, which would be a contract addition when the existing fields already say it honestly.

**Anchor:** `pyeye.resolver.resolve_handle` / `in_restricted_dir` / `RESTRICTED_DETAIL`; `pyeye.mcp.operations.expand._without_restricted`; `tests/test_restricted_symlink_results.py`; #999.

**Applies-to:**

- choke point 1: `pyeye.resolver.resolve_handle` (with `pyeye.resolver.in_restricted_dir`, `NotFound.restricted` and `pyeye.resolver.resolve_name`'s fall-through), and the not-found renderers that show its detail: `pyeye.mcp.operations.resolve._from_resolver`, `pyeye.mcp.operations.resolve.resolve`, `pyeye.mcp.operations.inspect.inspect`, `pyeye.mcp.operations.outline.outline`, `pyeye.mcp.operations.expand.expand` and `pyeye.mcp.operations.not_found.not_found`;
- choke point 2: `pyeye.mcp.operations.expand._without_restricted`, called by `pyeye.mcp.operations.expand.expand_resolved` (and so by `pyeye.mcp.operations.trace.trace`);
- `SECURITY.md` (path checks: results).

**Verify:** gold — `uv run pytest tests/test_restricted_symlink_results.py` passes. It checks:

- the venv and project symlinks into a restricted dir, and a project symlink into `~/.ssh`, are refused by resolve/inspect/outline with the restricted detail, and are missing from expand(imports)/trace and listed in `unresolved_imports`;
- `resolve_at` is refused;
- the real `/etc` case, when present;
- a base and a callee are reported in `unresolved_superclasses` / `unresolved_call_sites`;
- the no-loss-field drop warns;
- symlinks into allowed dirs and a symlinked project root are kept.
