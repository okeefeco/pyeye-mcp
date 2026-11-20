---
date: "2026-11-20"
title: "A module name matches its file only in exact case, on every filesystem (#1047)"
issues: [1047, 625, 1010, 933]
anchors: ["pyeye.project_layout._module_file_under", "pyeye.project_layout._exact_case", "pyeye.project_layout._is_case_sensitive", "pyeye.project_layout._entries", "pyeye.project_layout.clear_case_caches", "tests/test_module_case_exact.py"]
status: "active"
amends: ["2026-11-15-625-one-project-roots-policy-and-one-file-module-mapper-both.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-20 — A module name matches its file only in exact case, on every filesystem (#1047)

**Friction:** #1031's test `test_every_listed_spelling_resolves_back[pkg.dyn.Dyn]` failed on macOS 3.13 and 3.14 (run 44664234787). `resolve("pkg.Dyn")` answered "module `pkg.Dyn`" instead of the star re-exported class `pkg.dyn.Dyn`. The one module→file mapper's probe, `project_layout._module_file_under` (#625, extended with `.pyi` in #933), tested `Path.exists()`. On a case-insensitive filesystem (macOS APFS/HFS+ by default, Windows NTFS) that finds `pkg/dyn.py` for `pkg/Dyn.py`. Python's import system checks case on those filesystems and raises `ImportError`, so the answer was false, and it had been since #675.

**Decision:** approved by coordinator-3 (2026-11-20); fixed in #1031, which needs it.

- **Exact case, as Python's import requires.** A candidate file counts only if it `exists()` and every part below the search root (each package directory, then the `__init__.py`, `.py` or `.pyi` name) is a directory entry in exact case (`_exact_case`).
- **No cost on a case-sensitive filesystem.** `_is_case_sensitive(base)` probes each search root once. It respells the deepest part of the root that has a cased letter with its case swapped; if that names the same directory (`os.path.samefile`), the filesystem ignores case. Only then does the exact check list directories. A root with no cased part can't be probed, so it takes the exact check, which is always correct, just slower. On Linux `exists()` already matches case, and nothing is listed.
- **Listings are cached and see renames.** `_entries` caches a directory's names keyed on its mtime (an LRU of 4096), so a rename or a new entry, which changes the mtime, is seen on the next lookup without a watcher. A directory changed within the last 2 s isn't cached, because a further change in the same timestamp tick wouldn't move the mtime (the lesson of #1028's review).
- **Ownership (#717):** the probe and the comparisons live in `project_layout`; the path ratchet's baseline stays empty.
- **Limit:** the probe is per search root. A directory below a case-insensitive root that is itself case-sensitive (a Windows per-directory flag, a mounted volume) is still checked exactly, which is correct. The reverse, a case-insensitive directory below a case-sensitive root, isn't checked.

**Anchor:** `pyeye.project_layout._module_file_under` / `_exact_case` / `_is_case_sensitive` / `_entries`; `tests/test_module_case_exact.py`; #1047.

**Applies-to:**

- `pyeye.project_layout._module_file_under`, and through it `pyeye.project_layout.file_for_module` and every caller of the one mapper (the resolver's `definition_placement`, the re-export and import scans);
- `pyeye.project_layout._exact_case`, `pyeye.project_layout._is_case_sensitive`, `pyeye.project_layout._entries` and `pyeye.project_layout.clear_case_caches`.

**Verify:** gold — `uv run pytest tests/test_module_case_exact.py` passes; on macOS and Windows CI, so does `tests/test_one_star_rule.py`. It checks, on a stand-in case-insensitive filesystem (a `Path.exists` that ignores case):

- `pkg.Dyn`, `pkg.sub` and `PKG.dyn` find no file;
- the exact names still do, and `resolve("pkg.Dyn")` is the class `pkg.dyn.Dyn`;
- the probe finds a Linux temp dir case-sensitive, detects a case-insensitive one, takes the exact check when it can't tell, and runs once per root;
- a rename is seen; a settled directory is listed once; a recently changed one is listed again;
- a case-sensitive root lists nothing.
