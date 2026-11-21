---
date: "2026-11-22"
title: "Jedi's smart sys-path walk never adds a directory inside an import root (#1079)"
issues: [1079, 1078, 1048, 722, 858]
anchors: ["pyeye._jedi_project._filter_walk", "pyeye._jedi_project._without_inner_walk_entries", "pyeye._jedi_project.make_project", "tests/test_namespace_smart_path.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-22 — Jedi's smart sys-path walk never adds a directory inside an import root (#1079)

**Friction:** in Poetry 2.5.2, `src/poetry/` is a PEP 420 namespace. `imports`, `callees` and `superclasses` from any file inside it resolved no project import, even with `.pyeye.json` `{"packages": ["src"]}`.

- **Root cause.** Jedi's `smart_sys_path` walk (`jedi.Project._get_sys_path`) climbs from the analysed file, skipping directories with an `__init__.py`, and appends the first one without. Inside a namespace that is the namespace directory itself, `src/poetry`.
- **Why it broke imports.** Poetry keeps a module named after its namespace, `src/poetry/poetry.py`. On that path, `import poetry` finds the module, and a regular module beats namespace portions wherever they sit on the path (PEP 420). So `poetry.*` resolved to nothing.
- **Why the workaround couldn't help.** Adding `src` changes nothing: the walk's entries come after `added_sys_path`, and precedence doesn't depend on order anyway.
- **Confirmed** with raw Jedi on Poetry: only `smart_sys_path=False` plus `src` resolved `from poetry.utils.download import download_file`. The issue's minimal fixture reproduces it exactly once `src/pkg/pkg.py` exists.
- **Rejected suspects:** a split namespace with `poetry-core` absent is not it. The issue's path-less probe is not a fair control, because a path-less Script never gets `src` from the walk.

**Decision:** coordinator-3's approval of the proposal, 2026-11-22.

- `make_project` installs `_filter_walk` on each project it builds. That is an instance-level `_get_sys_path` wrapping the class's own method, so Jedi's cache still runs and a patched `jedi.Project` stays patchable. It drops a walk entry strictly inside one of the project's import roots, its `added_sys_path` (`src`, configured packages, namespace roots).
- **The principle:** a directory inside an import root is part of a package, never an import root of its own, so on `sys.path` it can only shadow.
- **What can be dropped:** only the walk's entries are candidates. The explicit base path, every added root (one may sit inside another) and the project root are always kept.
- **What stays as it was:** a flat layout, whose root is the project itself, keeps Jedi's walk, so a loose script still imports its sibling.
- **Rejected alternative:** `smart_sys_path=False` everywhere would also remove the walk from flat layouts.
- **Guarding a private Jedi method** (the coordinator's condition, as #1048 guards `check_sys_path_modifications`). Verified against Jedi 0.20.1.
  - **If it disappears:** when `jedi.Project._get_sys_path` is gone, `make_project` WARNS and leaves the walk unfiltered, today's behaviour, rather than crash.
  - **Tests** pin it three ways:
    - the hook exists and is overridden;
    - the filter drops the shadowing entry and keeps the explicit ones;
    - a behaviour test goes red when the override is bypassed (checked by mutation).
- **Interplay with #1048.** #1048 filters what `check_sys_path_modifications` returns: the `sys.path` changes in project code, which Jedi's `Importer` adds per import. This filters the Project's base path. Different inputs, so neither undoes the other. One limit follows from it: an inline `sys.path.insert` of an inner directory still reaches Jedi through #1048's path, unfiltered here.
- **Composes with #1078** (PR #1080), which makes `src` an import root for this layout with no config. That root is what the filter needs.

**Anchor:** `pyeye._jedi_project._filter_walk` / `_without_inner_walk_entries` / `make_project` / `_HAS_SYS_PATH_HOOK`; `jedi.Project._get_sys_path` (Jedi 0.20.1); #1079, #1078, #1048, #722.

**Applies-to:** `pyeye._jedi_project.make_project`, `pyeye._jedi_project._filter_walk`, `pyeye._jedi_project._without_inner_walk_entries`.

**Verify:** gold. `uv run pytest tests/test_namespace_smart_path.py` passes. It checks:

- on a namespace with `src/pkg/pkg.py`, `imports`, `callees` and `superclasses` resolve across the namespace;
- a flat layout's loose script still resolves its sibling;
- the hook exists and is overridden;
- the shadowing entry is dropped, while `src`, a nested configured root and the project root are kept;
- a missing hook falls back with a warning.

Forcing the fallback turns the behaviour tests red.
