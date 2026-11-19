---
date: "2026-11-20"
title: "A result whose file resolves into a restricted directory is refused wherever Jedi produces it (#999)"
issues: [999, 998, 993, 856, 909, 939, 626]
anchors: ["pyeye.resolver.resolve_handle", "pyeye.resolver.in_restricted_dir", "pyeye.resolver.restricted_path", "pyeye.mcp.operations.edges._resolve_call_target", "pyeye.mcp.operations.edges.superclass_bases", "pyeye.mcp.operations.inspect._build_signature", "pyeye.mcp.operations.typeref._resolve_head_via_jedi", "pyeye.path_utils.normalize_path_strict", "pyeye.mcp.operations.expand._without_restricted", "tests/test_restricted_symlink_results.py"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-20-1005-windows-fails-closed-only-on-a-link-loop.md"]
superseded_by: []
---

## 2026-11-20 — A result whose file resolves into a restricted directory is refused wherever Jedi produces it (#999)

**Friction:** found by the #998 security re-review of #993. Jedi follows symlinks while it looks up an import. A symlink inside the project (`proj/etcmod2 -> /etc/python3.12`), or inside the project venv's `site-packages` (#993 adds that place), was followed, and pyeye returned the target: `resolve`/`inspect` found it, and `expand(imports)`/`trace` emitted it as a stub or node. The input checks (#856, #909, #939) and the pruned walks never see this route. No code runs, but a repository could expose a restricted file's symbols and docstrings. Verified live against the real `/etc/python3.12/sitecustomize.py`.

**Decision:** the maintainer approved the design (via coordinator-3, 2026-11-20). Two rounds of adversarial review on #1003 then found paths that read a restricted file without going through the first two choke points, so the check moved to every place a Jedi name is produced.

- **One test, reused:** a result is refused when its file, RESOLVED (`path_utils.normalize_path`), is inside a restricted directory or a credential store, by `validation.restricted_dir`, the walkers' own prune test. That's `resolver.restricted_path` and `in_restricted_dir(name)`. It fails CLOSED: it resolves with `path_utils.normalize_path_strict`, where a symlink loop or any failure to follow a link raises and counts as restricted, and only a missing file falls back to a non-strict resolve (a dangling link into `/etc` still resolves there). A plain `normalize_path` isn't enough: from Python 3.13 a non-strict resolve no longer raises on a loop, it returns the unresolved path. Path normalisation stays in `path_utils` (#717). No new rule; a name with no file is never refused.
- **Where it applies:**
  1. `resolver.resolve_handle`, behind every canonical answer: resolve, resolve_at, inspect, outline, expand's and trace's sources and nodes, and plugin handle enrichment. A refused anchor is `NotFound("unresolved")` with `RESTRICTED_DETAIL` and an internal `restricted` flag. The operations show that detail instead of their default, and skip the #993 environment note after it. For a bare name, the policy's rules run first and the refusal is the fallback, so a legitimate same-named symbol still wins.
  2. `edges._resolve_call_target`, shared by `imports` and `callees`: a target in a restricted directory is refused there, where the caller still has its OWN spelling. `imports` lists it as written (`etcmod2.thing`), never as the canonical handle, which would name the restricted file's internals (`etcmod2._hidden_impl.thing`); `callees` counts it.
  3. `edges.superclass_bases`, the one walk behind the `superclasses` edge, `inspect`'s `superclasses` field and `edge_counts`, and the Pydantic plugin's `_mro`: a restricted base is unresolved, by the class's own text. So the field, the count and the edge agree, and `trace_model_inheritance` treats the MRO as unknown, as it does for any unresolved base, and reads no ancestor's fields.
  4. `inspect._build_signature`, used by `inspect`, every stub (`outline`, `expand`, `trace`): a signature defined in a restricted directory, or with a parameter that is (a subclass's inherited `__init__`, an alias of a restricted function), is skipped. The key is then omitted, the existing "no real signature" shape.
  5. `resolver._top_level_shadow`: a copy that resolves into a restricted directory is no candidate.
  6. `resolver.resolve_external_item` re-checks a cached answer on a hit.
  7. `typeref._resolve_head_via_jedi`, every annotation head (a parameter, a return type, an annotated module or class attribute, bare or attribute form like `K.Base`): a head in a restricted directory gets no handle, the TypeRef keeps the annotation's own text, as for any unresolved head. Its stdlib branch goes through the resolver.
- **Backstop:** `expand._without_restricted` drops any adjacent that still reaches `expand_resolved` with a logged warning, and counts it for `callees`. It never names it: a canonical handle could disclose restricted internals.
- **Not affected, checked:** docstrings (a project symbol's own docstring doesn't follow inference into the restricted file); the Flask and Django plugins, which call no `goto`/`infer`/`get_signatures` and read project files through the pruned walks or the resolver; `pydantic._resolved_kind`, which returns only a kind.
- **No new keys or reasons.** The closed not-found reason sets (#626) are unchanged; the honest reason is in `detail`.
- **Kept, by test:** symlinks into any other directory (project and venv), and a symlinked project root.
- **Rejected:**
  - checking each tool separately, which would mean many places to forget;
  - post-filtering only the final responses, which would leave trace's walk, signatures and plugin enrichment reading the file;
  - reporting refused adjacents by canonical handle, which discloses internals;
  - a new `restricted` reason or key.

**Anchor:** `pyeye.resolver.resolve_handle` / `in_restricted_dir` / `restricted_path` / `RESTRICTED_DETAIL`; `pyeye.mcp.operations.edges._resolve_call_target` / `superclass_bases`; `pyeye.mcp.operations.inspect._build_signature`; `pyeye.mcp.operations.expand._without_restricted`; `tests/test_restricted_symlink_results.py`; #999.

**Applies-to:**

- the canonical answer: `pyeye.resolver.resolve_handle` (with `NotFound.restricted`, `pyeye.resolver.resolve_name`'s fall-through, `pyeye.resolver._top_level_shadow` and `pyeye.resolver.resolve_external_item`), and the not-found renderers that show its detail: `pyeye.mcp.operations.resolve._from_resolver`, `pyeye.mcp.operations.resolve.resolve`, `pyeye.mcp.operations.inspect.inspect`, `pyeye.mcp.operations.outline.outline`, `pyeye.mcp.operations.expand.expand`, `pyeye.mcp.operations.not_found.not_found`;
- where Jedi names are produced: `pyeye.mcp.operations.typeref._resolve_head_via_jedi` (TypeRef heads), `pyeye.mcp.operations.edges._resolve_call_target` (imports, callees), `pyeye.mcp.operations.edges.superclass_bases` (the superclasses edge, inspect's field and count, `pyeye.plugins.pydantic.PydanticPlugin.trace_model_inheritance`), `pyeye.mcp.operations.inspect._build_signature` (inspect and every stub);
- the resolved-path test: `pyeye.resolver.restricted_path` over `pyeye.path_utils.normalize_path_strict`;
- the backstop: `pyeye.mcp.operations.expand._without_restricted`, called by `pyeye.mcp.operations.expand.expand_resolved` (and so by `pyeye.mcp.operations.trace.trace`);
- `SECURITY.md` (path checks: results).

**Verify:** gold — `uv run pytest tests/test_restricted_symlink_results.py` passes. It checks:

- the venv and project symlinks into a restricted dir, and a project symlink into `~/.ssh`, are refused by resolve/inspect/outline with the restricted detail, missing from expand(imports)/trace, and listed in `unresolved_imports`;
- `resolve_at` and the real `/etc` case (when present);
- base and callee losses;
- the #1003 review's cases: an inherited signature and an alias's signature in inspect/outline/members/trace; inspect's `superclasses` field and count agree with the edge; loss fields carry the importer's spelling, not `_hidden_impl`; no restricted shadow candidate; Pydantic `trace_model_inheritance` reads no restricted ancestor;
- TypeRef heads in every form get no restricted handle;
- a symlink loop fails closed on every Python (3.12 and 3.13+), a missing file isn't refused, and a dangling link into a restricted dir is;
- symlinks into allowed dirs and a symlinked project root are kept.

With the new checks patched out, every refusal test fails.
