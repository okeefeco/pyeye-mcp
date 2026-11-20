---
date: "2026-11-20"
title: "A repository's network paths are refused lexically, before any filesystem call (#1048)"
issues: [1048, 993, 998, 1035, 1045, 856]
anchors: ["pyeye.path_utils.network_path", "pyeye.environment._pth_paths", "pyeye.declared_deps._anchored", "pyeye.config.ProjectConfig._without_network", "tests/test_network_paths.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-20 — A repository's network paths are refused lexically, before any filesystem call (#1048)

**Friction:** pyeye reads paths a cloned repository supplies (a `.pth` line in its `.venv`, a declared dependency, its config files) and looked each one up (`is_dir()`, `exists()`, `resolve()`) before the restricted-path check. On Windows, looking up `\\host\share\x` is itself an SMB connection to that host, which can leak the user's NTLM credentials. The check couldn't simply move first: it needs the resolved form, and resolving a UNC path is the network call.

**Decision** (coordinator-3, with the user's ruling of 2026-11-20 on scope):

- **One lexical predicate,** `pyeye.path_utils.network_path(path)`. It returns why a path is refused, or `None`, and never touches the filesystem. On Windows it refuses:
  - UNC paths (`\\host\share`, `//host/share`);
  - device and extended paths (`\\?\…`, `\\?\UNC\…`, `\\.\…`);
  - drive-relative paths (`C:pkg`);
  - root-relative paths (`\pkg`), which are on the current drive, and that drive is a share when the server's cwd is on one.

  On POSIX nothing is refused: `//x` is local there and `\` is a filename character.
- **Called first** wherever a repository supplies a path, as written, before it is joined, expanded or looked up. A refused entry is skipped with a warning, the same way a restricted path is.
- **Reported, not hidden:** a refused entry of the project's own config files is in `rejected_paths` with its reason. The save layer keeps it as written, so a save doesn't silently delete it (#1038).
- **Agent-supplied inputs are the user's choice and are not refused** (ruled 2026-11-20). That covers `project_path`, `file` and the other tool arguments, `configure_packages` additions, and the user's global config. Analysing a project on a share stays possible. `PathValidator` is unchanged; refusing at that boundary later would be one call.
- **Honest limits:** a mapped network drive (`Z:\`) and a symlink or junction that points at a share can't be detected lexically. On POSIX, an automounter path such as `/net/host` is a mount trigger, outside this rule.

**Anchor:** `pyeye.path_utils.network_path`; `pyeye.environment._pth_paths`; `pyeye.declared_deps._anchored`; `pyeye.config.ProjectConfig._without_network`; #1048.

**Applies-to:**

- `.pth` lines: `pyeye.environment._pth_paths`;
- declared dependencies (#1035): `pyeye.declared_deps._anchored`, `pyeye.declared_deps._members` and `pyeye.declared_deps._file_url_path`;
- the project's config files (`.pyeye.json` and the other project config files, and `.pyeye.override.json`): `packages`, `namespaces`, `standalone.dirs` and `environment`, in `pyeye.config.ProjectConfig._load_from_file` through `_without_network`;
- `[tool.pyright]` extra paths and build-backend layouts: `pyeye.config.ProjectConfig._read_pyright_extra_paths` and `_add_detected_paths`;
- an editable install's finder targets (#1045, not merged when this was decided): whichever of #1045 and #1048 lands second adds the call.

**Verify:** gold. `uv run pytest tests/test_network_paths.py` passes. It covers:

- every refused and allowed form, with Windows rules forced on any platform, and the predicate never touching the filesystem;
- each call site with a UNC entry, while a spy records any filesystem call on a path naming the host, and none may happen;
- the `rejected_paths` record, the save layer keeping the entry, and the global config not being refused.

Partial for real Windows: the SMB connection itself is not observed. The tests prove that no lookup reaches the filesystem, which is what opens the connection.
