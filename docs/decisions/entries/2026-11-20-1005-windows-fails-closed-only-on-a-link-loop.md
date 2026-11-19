---
date: "2026-11-20"
title: "On Windows, restricted_path fails closed only on a link loop; other strict-resolve errors fall back, still checked (#1005)"
issues: [1005, 999]
anchors: ["pyeye.resolver.restricted_path", "pyeye.resolver._is_link_loop", "tests/test_restricted_path_windows.py"]
status: "active"
amends: ["2026-11-20-999-results-resolving-into-a-restricted-directory-are-refused.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-20 — On Windows, restricted_path fails closed only on a link loop; other strict-resolve errors fall back, still checked (#1005)

**Friction:** found by the final security review of #1003 (#999), by reading the code. `restricted_path` counted every `OSError` from `path_utils.normalize_path_strict` (except a missing file) as restricted. On Windows a strict resolve also fails where a normal resolve and Jedi succeed: access denied on a parent directory, a reparse point it can't follow (a `WindowsApps` app-exec alias), an invalid name. So readable files were refused (not found, or an unresolved loss). It's a wrong refusal, never a leak.

**Decision:**

- **The deny-list does apply on Windows,** so the check can't be skipped there. The fixed system patterns are POSIX and never match a drive-letter path. But the credential-store rule matches below the server's OWN home in any spelling (`C:/Users/alice/.ssh/id_rsa`, case ignored), as `_credential_pattern` adds `Path.home()` (verified). Returning early on `os.name == "nt"` would drop that protection, so it was rejected.
- **On Windows only a link loop fails closed:** `errno.ELOOP`, `winerror` 1921 (`ERROR_CANT_RESOLVE_FILENAME`), or `RuntimeError` before Python 3.13. Any other `OSError` falls back to the non-strict `path_utils.normalize_path`, and that result is checked by `validation.restricted_dir` as usual. A failing fallback fails closed.
- **A link into a credential store is still refused.** That's a junction, symlink or other reparse point into `~/.ssh` whose STRICT resolve fails for another reason, such as access denied on a component. The fallback's non-strict resolve still follows every link Windows can follow (Python's `ntpath.realpath` reads the link with `readlink` when the final path name can't be opened), so the checked result is the target inside the store, and it's refused. A link Windows can't follow can't be opened either, so neither the resolve nor Jedi reaches anything through it. Tested both ways: a simulated failing strict resolve whose fallback lands in `.ssh`, and, on the Windows runners, a real `mklink /J` junction into a credential store.
- **POSIX is unchanged:** every strict-resolve error still counts as restricted, as #1003's review verified.
- **What users see:** only fewer wrong refusals on Windows. No new keys, reasons or messages.

**Anchor:** `pyeye.resolver.restricted_path` / `_is_link_loop` / `_ON_WINDOWS`; `tests/test_restricted_path_windows.py`; #1005.

**Applies-to:**

- `pyeye.resolver.restricted_path` (and through it `pyeye.resolver.in_restricted_dir`, used at every #999 check site);
- `pyeye.resolver._is_link_loop`;
- `SECURITY.md` (path checks: results).

**Verify:** gold — `uv run pytest tests/test_restricted_path_windows.py` passes, on every OS for the policy, and on the Windows CI runners for the real cases. It checks:

- on "Windows", access denied, winerror 5 and an invalid name fall back and aren't refused;
- the fallback is still checked (a credential store is refused), including a link whose strict resolve fails but whose fallback lands in `.ssh`;
- a loop (`ELOOP`, winerror 1921, `RuntimeError`) and a failing fallback fail closed;
- POSIX fails closed on every error;
- on real Windows, a plain file isn't refused, the server's own `.ssh` is, a symlink loop is (when symlinks are allowed), a junction into a credential store is, and a `WindowsApps` alias isn't (when present).
