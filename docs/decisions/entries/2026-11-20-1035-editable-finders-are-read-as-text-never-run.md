---
date: "2026-11-20"
title: "An editable install's import-hook finder is read as text for its targets, never run (#1035)"
issues: [1035, 993, 998]
anchors: ["pyeye.environment._finder_paths", "pyeye.environment._finder_module_roots", "pyeye.environment._parse_finder", "pyeye.environment._finder_targets", "pyeye.environment._root_for", "pyeye.environment._pth_paths", "tests/test_editable_finders.py"]
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

- **Which module:** `_pth_paths` collects, per `.pth` file, the module names of its `import M[; ...]` lines (M a plain undotted name), deduplicated. It never parses them, so its cache (keyed on the `.pth` file's stat) can't serve a finder that changed on its own. Anything else on an import line still adds nothing.
- **Read once per environment, and charged** (security review, HIGH: the first cut parsed `M.py` again for every import line, and charged nothing for it, so a 1 MiB finder named by thousands of lines cost hours):
  - `site_paths` reads each named module at most once per environment;
  - it reads at most `MAX_FINDER_MODULES` (32) per environment;
  - it charges each read `FINDER_LOOKUP_COST` (one lookup per KiB of the cap) plus one per root against `MAX_PTH_LOOKUPS`;
  - parses are memoised across calls on `(path, device, inode, mtime, size)`.
- **The read** (`_finder_module_roots`):
  - only `M.py` in the `.pth` file's own directory;
  - opened with `O_NOFOLLOW` (or, where the OS lacks it, refused if it's a symlink) and checked with `fstat` on the same descriptor (a regular file of at most `MAX_FINDER_BYTES`, 64 KiB), so a swap between check and read can't redirect it;
  - opened `O_NONBLOCK` (`_open_regular`), so a FIFO or device named as a finder can't block discovery waiting for a writer (final security pass, MEDIUM). The `.pth` reader uses the same helper, which also closes #993's identical hang for a FIFO named `*.pth`;
  - read with one bounded `read`;
  - memoised on `(path, device, inode, mtime, ctime, size)`. The ctime catches a same-size in-place rewrite whose mtime was restored with `os.utime` (final pass, LOW). Roots are re-checked on every call anyway.
- **Parsed, never run** (`_parse_finder`): it's parsed with `ast`, never imported. A parse failure, including pathological nesting (`SyntaxError`, `RecursionError`, `MemoryError`), adds nothing. At most `MAX_PTH_LINES` roots come from one finder.
- **Only two shapes**, at module level (`_finder_targets`):
  1. an assignment to `MAPPING` (`{str: str}`) or `NAMESPACES` (`{str: [str, ...]}`);
  2. an expression statement calling `<anything>.map_module(str, str)`, with exactly two positional args and no keywords.

  Every key and value must be a plain string literal. An f-string, name, expression, call or `**` splat makes that statement add nothing.
- **Target to root** (`_root_for`): a target is a package directory, a package's `__init__.py` (asked of `project_layout.package_kind`, the one package predicate, only for a `.py`), or a module file, given absolute. Its root is the directory above it, and only when the mapped name (an undotted identifier) is the target's own name, so the root imports it under that name.
  - A target directly in a home directory therefore makes the home an import root, exactly as a plain `.pth` line naming it could (security review, informational). The resolved-form check below still applies.
- **Checks:** each root gets the same resolved-form `unwalkable_root` check as a `.pth` path (#998), and counts toward `MAX_SITE_PATHS`.
- **Rejected:**
  - importing or executing the finder (it is the analysed repository's code);
  - reading `direct_url.json` as a fallback: it names the project root, not its import root;
  - following a symlinked `M.py`.
- **Known limits** (informational, final pass; each needs a concurrent local attacker):
  - Windows has no `O_NOFOLLOW`, so the symlink refusal is an `is_symlink` check before `open`, and racy;
  - a swap of a PARENT directory component between listing and open isn't covered (`openat` with `dir_fd` would cover it).
- **Filed separately:** on Windows, a UNC target is touched before the path check, both for a `.pth` line and for a finder root (#1048). It predates this, and the fix must refuse UNC paths lexically.

**Anchor:** `pyeye.environment._finder_roots` / `_finder_targets` / `_root_for` / `_pth_paths`; #1035, #993, #998.

**Applies-to:** `pyeye.environment._finder_roots`, `pyeye.environment._finder_targets`, `pyeye.environment._root_for`, `pyeye.environment._pth_paths`.

**Verify:** gold. `uv run pytest tests/test_editable_finders.py tests/test_project_environment.py` passes. It checks:

- both setuptools literals and the editables calls are recovered, and a project's import of the editable package resolves;
- the finder is never imported (a marker file stays absent);
- non-literal values, extra or keyword `map_module` args, an oversized or pathologically nested finder, a target in `/etc` or a credential store, a symlinked finder, a module that's dotted, absent or not beside the `.pth` file, and a mapped name that isn't the target's own all add nothing, each test next to a valid target that is kept;
- finder targets count toward the lookup ceiling, with distinct parents so dedup can't hide it;
- a finder named by 5,000 repeated lines, or by 200 `.pth` files, is parsed once; an unchanged finder isn't reparsed across calls; a finder that changes alone is re-read; at most `MAX_FINDER_MODULES` are read; and a ~64 KiB finder named by 20 files of 5,000 lines stays within a time threshold;
- the finder size cap is far below the `.pth` cap;
- a FIFO named as a finder, and a FIFO named `*.pth`, don't block (each test runs on a thread with a 10 s join);
- a same-size rewrite with its mtime restored is re-read.
