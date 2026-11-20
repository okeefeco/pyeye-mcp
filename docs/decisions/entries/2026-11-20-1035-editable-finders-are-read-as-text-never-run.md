---
date: "2026-11-20"
title: "An editable install's import-hook finder is read as text for its targets, never run (#1035)"
issues: [1035, 993, 998]
anchors: ["pyeye.environment._finder_roots", "pyeye.environment._finder_targets", "pyeye.environment._root_for", "pyeye.environment._pth_paths", "tests/test_editable_finders.py"]
status: "active"
amends: ["2026-11-19-993-the-project-environment-is-discovered-and-read-statically.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-20 — An editable install's import-hook finder is read as text for its targets, never run (#1035)

**Friction:** #993 reads an environment's `.pth` plain-path lines and skips every import line, because pyeye never runs the environment's code. A repository can ship its own `.venv` (#998). #1035 removed sibling-directory guessing, so an editable install became the way a neighbouring package reaches Jedi.

Measured per build backend with `uv pip install -e` (#1035): every backend writes a plain path for a `src/` layout, and most do for a flat one. Three write an import line, and their packages were invisible:

- setuptools with a flat layout: `import __editable___<n>_finder; ...install()`. Its module holds `MAPPING: dict[str, str]` and `NAMESPACES: dict[str, list[str]]` literals.
- hatchling with `dev-mode-exact`;
- pdm-backend with `editable-backend = "editables"`. This one and hatchling's write `import _editable_impl_<n>`, whose module calls `F.map_module(name, path)` with string literals.

**Decision:** the coordinator's approved proposal, with the review constraints (via coordinator-3, 2026-11-20).

- **Which module:** for a `.pth` line `import M[; ...]`, with M a plain undotted name, `_finder_roots` reads `M.py`. Only from the `.pth` file's own directory, only if it isn't a symlink, and only if it's at most `MAX_PTH_BYTES`. Anything else on an import line still adds nothing.
- **Parsed, never run:** it's parsed with `ast`, never imported. A parse failure, including pathological nesting (`SyntaxError`, `RecursionError`, `MemoryError`), adds nothing.
- **Only two shapes**, at module level (`_finder_targets`):
  1. an assignment to `MAPPING` (`{str: str}`) or `NAMESPACES` (`{str: [str, ...]}`);
  2. an expression statement calling `<anything>.map_module(str, str)`, with exactly two positional args and no keywords.

  Every key and value must be a plain string literal. An f-string, name, expression, call or `**` splat makes that statement add nothing.
- **Target to root** (`_root_for`): a target is a package directory, a package's `__init__.py` or a module file, given absolute. Its root is the directory above it, and only when the mapped name (an undotted identifier) is the target's own name, so the root imports it under that name.
- **Bounds and checks:** each root joins the `.pth` file's deduplicated path list. So it counts toward `MAX_PTH_LINES` and `MAX_SITE_PATHS`, and gets the same resolved-form `unwalkable_root` check (#998).
- **Rejected:**
  - importing or executing the finder (it is the analysed repository's code);
  - reading `direct_url.json` as a fallback: it names the project root, not its import root;
  - following a symlinked `M.py`.
- **Known limit:** the `.pth` cache (#993) keys on the `.pth` file's stat, not the finder's. A reinstall rewrites both.

**Anchor:** `pyeye.environment._finder_roots` / `_finder_targets` / `_root_for` / `_pth_paths`; #1035, #993, #998.

**Applies-to:** `pyeye.environment._finder_roots`, `pyeye.environment._finder_targets`, `pyeye.environment._root_for`, `pyeye.environment._pth_paths`.

**Verify:** gold. `uv run pytest tests/test_editable_finders.py tests/test_project_environment.py` passes. It checks:

- both setuptools literals and the editables calls are recovered, and a project's import of the editable package resolves;
- the finder is never imported (a marker file stays absent);
- non-literal values, extra or keyword `map_module` args, an oversized or pathologically nested finder, a target in `/etc` or a credential store, a symlinked finder, a module that's dotted, absent or not beside the `.pth` file, and a mapped name that isn't the target's own all add nothing, each test next to a valid target that is kept;
- finder targets count toward the lookup ceiling.
