---
date: "2026-11-16"
title: "MCP responses spell in-project paths under the caller's project_path; the validator no longer resolves it (#717)"
issues: [717, 714, 603]
anchors: ["pyeye.mcp.server._for_caller", "pyeye.path_utils.respell_paths", "pyeye.path_utils.absolute_path", "pyeye.validation.PathValidator.validate_path"]
status: "active"
amends: ["2026-11-15-714-roots-keep-the-callers-spelling-comparisons-resolve-and-a.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — MCP responses spell in-project paths under the caller's project_path; the validator no longer resolves it (#717)

**Friction:** The #714 entry left open whether a Jedi-derived `location.file` should keep the caller's spelling. Under a symlinked project (`~/code` → `/Volumes/…`) every location came back as the real path, which an agent can't match to its own paths or to its sandbox's allowed directories. Two things did it: `PathValidator.validate_path` resolved every absolute `project_path` / `file` argument, and Jedi reports files resolved. `ProjectManager.get_analyzer` also builds its one analyzer per directory from the resolved root, by design (#603). #737's boundary walker allow-listed the five resulting violations against #717.
**Decision:** This amends the #714 entry and closes its open question: the agent gets the caller's spelling.

- `validate_path` still runs its security checks on the **resolved** form (a link to `/etc` is rejected), but returns the caller's spelling made absolute (`path_utils.absolute_path`: `abspath`, not `resolve`).
- At the MCP boundary, `server._for_caller` re-spells every in-project path of a core tool's response (`resolve`, `resolve_at`, `inspect`, `expand`, `outline`, `trace`) under the given `project_path` (`path_utils.respell_paths` → `respell_under`: containment resolved, the answer joined onto the caller's root). Paths outside the root are unchanged. This is one place, because the analyzer is shared across spellings and can't know which spelling a call used.
- Jedi-facing paths stay resolved (#714). Only the response is re-spelled.

Rejected: building one analyzer per spelling (it undoes #603's single cache per directory); re-spelling in each operation (they don't know the caller's spelling).
**Anchor:** `pyeye.mcp.server._for_caller`; `pyeye.path_utils.respell_paths`, `respell_under`, `absolute_path`; `pyeye.validation.PathValidator.validate_path`; #717, #714, #603.
**Applies-to:** the six core tools' return values in `pyeye.mcp.server` (`resolve`, `resolve_at`, `inspect`, `expand`, `outline`, `trace`), and `validate_mcp_inputs`' path arguments (`file`, `file_path`, `path`, `project_path`) via `validate_path`. Plugin tools already list files under the caller-spelled root. The operations under `mcp/operations` return resolved Jedi paths, and only the MCP layer re-spells.
**Verify:** gold: `uv run pytest tests/test_caller_spelling.py tests/test_mcp_path_boundary.py` passes, with `KNOWN_SPELLING_GAPS` empty. The symlink runs assert that every in-project file is spelled under the caller's root, and `test_validate_path_still_rejects_by_the_resolved_form` checks the security side.
