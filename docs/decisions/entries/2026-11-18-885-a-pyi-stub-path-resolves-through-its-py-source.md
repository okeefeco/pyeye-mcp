---
date: "2026-11-18"
title: "A .pyi stub path resolves through the .py beside it; a stub-only file stays unresolved, saying why (#885)"
issues: [885, 882, 625, 602, 933]
anchors: ["pyeye.mcp.operations.resolve._resolve_file_only", "pyeye.mcp.operations.resolve._resolve_at_position", "pyeye.mcp.operations.resolve._parse_identifier", "pyeye.mcp.operations.not_found._path_hint", "tests/test_resolve_pyi_stubs.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-18 — A .pyi stub path resolves through the .py beside it; a stub-only file stays unresolved, saying why (#885)

**Friction:**

- `resolve("pkg/mod.pyi")` was `unresolved` even with `pkg/mod.py` beside it. The file↔module mapper (`module_name_for_file`, #625) names `.py` files only.
- `resolve("pkg/mod.pyi:3")` and `resolve_at` on the stub already landed on the `.py` definition, because Jedi's `goto` follows a stub to its source. So one file form disagreed with the other two.
- #884's stop-gap hint sent every `.pyi` to its `.py` spelling, including a stub-only file, for which that path doesn't exist.

**Decision:**

- **A stub beside its source** resolves, in the file-only form, as that `.py` does: the same handle, kind, scope and location (the `.py`). That matches what the `file:line` and `resolve_at` forms report. It's additive: a miss becomes found, and no field changes shape.
- **The mapper stays `.py`-only (#625).** `_resolve_file_only` swaps a stub for its sibling `.py` before mapping, so there's still one file↔module mapper.
- **A stub-only file** (no `.py` beside it) stays `unresolved` in every file form: the path, `file:line`, and `resolve_at` when the position doesn't resolve. Its detail says it's a stub with no `.py` source, and that a module whose source lives elsewhere resolves by its dotted name.
  - A handle for it would be one that `inspect`, `expand`, `outline` and dotted `resolve` all reject. That breaks the round-trip invariant (#602).
  - A stub line that points at a resolvable name, such as `import os`, still resolves. Only a miss gets the stub-only detail.
- **External stubs**, from typeshed or a `foo-stubs` package, take the stub-only path too. Pinned in tests.
- **Identifier parsing:** a `.pyi` suffix makes the identifier a file path, as `.py` does, so a bare `mod.pyi` is a file, not the dotted name `mod.pyi`. `not_found.SOURCE_SUFFIXES` is the one list both modules use.
- **Hints:** `_path_hint` passes a stub to `resolve` as it is, never as a `.py` that may not exist.
- **Not decided here:** giving stub-only modules handles across the whole surface. That's a contract change, filed as #933.

**Anchor:** `pyeye.mcp.operations.resolve._resolve_file_only` / `_resolve_at_position` / `_parse_identifier`; `pyeye.mcp.operations.not_found._path_hint`; `tests/test_resolve_pyi_stubs.py`; #885.

**Applies-to:**

- `pyeye.mcp.operations.resolve._resolve_file_only`, `_resolve_at_position` (and through it `_resolve_file_line` and `resolve_at`), and `_parse_identifier`.
- `pyeye.mcp.operations.not_found._path_hint`, `_default_detail` and `SOURCE_SUFFIXES`.

**Verify:** gold — `uv run pytest tests/test_resolve_pyi_stubs.py tests/test_not_found_path_hint.py` passes. It checks:

- a paired stub resolves identically to its `.py`, relative and absolute, and its handle round-trips through `inspect`;
- `file:line` and `resolve_at` on a stub still match the source;
- every stub-only file form is `unresolved`, with the stub-only detail and no non-existent `.py` named;
- a stub-only module has no handle in `resolve`, `inspect` or `submodules`;
- a resolvable stub line still resolves;
- typeshed and `-stubs` paths are stub-only misses;
- `.pyi` identifiers parse as files.
