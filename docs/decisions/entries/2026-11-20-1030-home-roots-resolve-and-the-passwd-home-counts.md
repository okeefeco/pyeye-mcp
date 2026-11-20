---
date: "2026-11-20"
title: "A symlinked home root is matched where it points, and the passwd home counts as the server's own (#1030)"
issues: [1030, 1019, 909]
anchors: ["pyeye.validation._resolved_home_roots", "pyeye.validation._home_root", "pyeye.validation._passwd_home", "pyeye.validation._homes", "pyeye.validation._build_credential_stores", "pyeye.validation._dir_key", "pyeye.validation._store_key", "tests/test_credential_home_roots.py"]
status: "active"
amends: ["2026-11-20-1019-restricted-on-any-form-and-linked-stores.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-20 — A symlinked home root is matched where it points, and the passwd home counts as the server's own (#1030)

**Friction:** the security review of #1028 found two gaps that predate it.

- **A symlinked home root.** `USER_HOMES` matches a home only by its spelling (`^/home/[^/]+/`). On a BSD-style system `/home` points at `/usr/home`. The walkers judge resolved forms, so a walk of `/home/bob` reached `/usr/home/bob/.ssh`, which no pattern named, and descended into it.
- **A `$HOME` that isn't the passwd home.** Only `$HOME`'s stores were recorded as links. A service started with `HOME=/srv/app` left the user's real `~/.ssh -> /data/keys` unmatched at its target.

**Decision:** ruled by coordinator-3 (2026-11-20) as within the #999/#1019 policy; no new key or reason.

- **Resolved home roots.** Each `USER_HOMES` pattern is read as a root (`_home_root`: `^/home/[^/]+/` is the directory of homes `/home`; `^/root/` is one home). Each root is resolved once per store build. Where the resolved form differs, it becomes a home pattern of the same shape (`^/usr/home/[^/]+/`). A test fails if any `USER_HOMES` pattern can't be read as a root, so one can't silently lose its resolved form.
- **The passwd home.** `_passwd_home()` (`pwd.getpwuid(os.getuid()).pw_dir`, POSIX, read once per process) is a home like `$HOME`: matched as spelled and as resolved, and its links are recorded.
  - Both homes are in the cache key (`_homes`), so a relink below the passwd home is seen at once, as #1019 does for `$HOME`.
  - In the usual case the two are the same and dedupe, so the cheap key's cost is unchanged: two `stat` calls.
  - When they differ, it costs two more `stat` calls per lookup, and the full key costs one `readlink` per store path of each home.
- **Out of scope, documented:**
  - **Other users' store links** (`/home/bob/.ssh -> /data/bob`). They stay matched by spelling only: finding them would mean reading every user's home on each rebuild, and keying on every home's links.
  - **A home root relinked after start-up.** The root is read when the stores are built. So a relink is seen at the next rebuild, which comes when the server's own store directories change, or after a restart. The cheap key doesn't watch `/`.

**Anchor:** `pyeye.validation._resolved_home_roots` / `_passwd_home` / `_homes`; `tests/test_credential_home_roots.py`; #1030.

**Applies-to:**

- `pyeye.validation._build_credential_stores`, `pyeye.validation._StoreCache` (its keys `_dir_key` and `_store_key`), and through them `credential_path`, `restricted_reason`, `restricted_dir`, `pyeye.async_utils.pruned_walk` and `pyeye.resolver.restricted_path`;
- `SECURITY.md` (the credential-store paragraph and its limits).

**Verify:** gold. `uv run pytest tests/test_credential_home_roots.py tests/test_restricted_any_form.py` passes. It checks:

- a store at a symlinked root's resolved form is refused and pruned, and a walk through the link skips it;
- a single-home root resolves as one home;
- every `USER_HOMES` pattern reads as a root;
- the passwd home's linked store is refused at its target, its stores are refused by spelling, and a relink below it is seen;
- the same home costs no extra `stat`;
- another user's store link is pinned as matched by spelling only.
