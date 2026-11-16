---
date: "2026-11-17"
title: "The project scan excludes nested independent repositories, unless .gitmodules declares them (#810)"
issues: [810, 507, 517]
anchors: ["pyeye.async_utils.filtered_rglob", "pyeye.async_utils._is_nested_repo", "pyeye.async_utils._declared_submodules", "pyeye.async_utils.rglob_async"]
status: "active"
amends: ["2026-08-09-507-the-project-scan-excludes-nested-git-worktrees-not.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-17 — The project scan excludes nested independent repositories, unless .gitmodules declares them (#810)

**Friction:** #507 excluded nested linked worktrees and named the rest as known residue: *"this rule does not catch a vendored nested clone, which is noise by the same logic; left unsolved rather than guessed at."* Our own workflow then hit it. `pyeye-scenarios` provisions clones in-repo under the gitignored `.scenario-repos/`, so a django clone put 2,922 `.py` files into pyeye-on-pyeye analysis. Its deliberately broken `tests_syntax_error.py` surfaced as `unparseable_files` in this repo's import graph, and `test_the_pyeye_repo` failed (#810).

**Decision:** This is the user's decision on #810 (option 1). `filtered_rglob`, the one home of the scan rule (#517), also prunes any directory **strictly below** the scan root whose `.git` is a **directory**, unless a `.gitmodules` declares it as a submodule.

- **A clone is another project.** #507's invariant was "don't index nested checkouts", and this applies it to the remaining kind.
- **Submodules stay included.** One written by git 1.7.8 or later has a `.git` *file*, so it is never matched. An older one, with a `.git` directory, is kept by its `path = …` entry in a `.gitmodules`. The entry may be at the scan root, in one of its ancestors (a project inside a superproject), or in a directory met during the walk, read relative to that directory. Each `.gitmodules` is read as text, so there is no git dependency, and an unreadable file declares nothing.
- **Linked worktrees** stay #507's rule (a `.git` file whose gitdir has `commondir`).
- **The scan root is never tested.** A project is normally a clone, and pointing pyeye at a clone or a worktree behaves as before.
- **`configure_packages` is how a user indexes a nested clone on purpose.** Each package is walked from its own root, where this rule never applies.
- **Still rejected: `.gitignore` / `git check-ignore`**, for #507's reasons (a git dependency on the scan path, breaking non-git projects, dropping gitignored-but-imported generated code). This rule keys on git's on-disk structure, not on ignore patterns.
- **Classification under 2.x (#629): Changed, not breaking.** It changes which files a scope covers, but no tool's signature or response shape. A user who relied on a nested clone being indexed restores it with `configure_packages`.

Known residue: `configure_packages` on a clone **under a dot-directory** (e.g. `.scenario-repos/x`) lists its files in the `packages` scope, but its symbols still don't resolve. This predates this change and is reported separately. A clone at a plain path, or a sibling, resolves.

**Anchor:** `pyeye.async_utils.filtered_rglob`, `_is_nested_repo`, `_declared_submodules`, `rglob_async`; #810, #507, #517.
**Applies-to:** every site that enumerates project files through `filtered_rglob`:

- `pyeye.async_utils.rglob_async`, and through it `pyeye.scope_utils.parallel_search` (behind `JediAnalyzer.get_project_files`), `LazyNamespaceLoader._load_namespace`, and `PluginBase.get_project_files`;
- `pyeye.project_manager.ProjectManager._catch_up`;
- `pyeye.canonicalization._build_binding_index`;
- the plugin scans `PydanticPlugin.detect`, `FlaskPlugin.detect`, `FlaskPlugin.get_framework_components`, `DjangoPlugin.get_framework_components` and `DjangoPlugin.find_migrations`.

**Verify:** gold. `uv run pytest tests/unit/utils/test_async_utils.py tests/integration/test_nested_worktree_exclusion.py` passes.

- `TestRglobNestedIndependentRepos` covers a clone excluded at any depth, a plain subdirectory kept, a clone as the scan root kept, an old-style submodule kept by `.gitmodules` (an undeclared sibling clone dropped), a quoted path, and `.gitmodules` above the root and in a nested superproject.
- `TestNestedIndependentClones` builds real `git clone` and `git submodule add` layouts. The clone is excluded from `main` and `all`, the submodule and a plain directory are kept, and `configure_packages` on a plain-path clone makes its class resolve.
- Against the pre-change rule, 7 of these fail.
