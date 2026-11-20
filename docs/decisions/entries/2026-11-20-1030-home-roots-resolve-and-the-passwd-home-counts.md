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

- **Resolved home roots.** Each `USER_HOMES` pattern is read as a root (`_home_root`: `^/home/[^/]+/` is the directory of homes `/home`; `^/root/` is one home). Where the resolved form differs, it becomes a home pattern of the same shape (`^/usr/home/[^/]+/`). A test fails if any `USER_HOMES` pattern can't be read as a root, so one can't silently lose its resolved form. From the security review of #1051:
  - **Resolved once per process, before the lock.** `_resolved_roots` keeps successful resolves only, and `_StoreCache` calls `_resolved_home_roots()` before taking its lock. Resolving on every rebuild under the lock would let one hard-down NFS `/home` block every input check, result check and walk; the reviewer measured a second caller waiting the full 3 s of a slow resolve. A first resolve can still block its own caller once.
  - **A failed resolve fails toward the spelling.** It is logged and retried at the next rebuild, and the spelled root still applies meanwhile.
  - **A root resolving to `/` is skipped:** `^/[^/]+/` would make every top-level directory a home.
- **The passwd home.** `_passwd_home` (`pwd.getpwuid(os.getuid()).pw_dir`, POSIX) is a home like `$HOME`: matched as spelled and as resolved, and its links are recorded. From the review:
  - **Only a success is kept.** A failed lookup (LDAP or SSSD down) is retried after 5 s, then twice as long each time up to 5 min. A lookup already running in another thread answers `None` rather than blocking. Caching a failure, as `functools.cache` did, failed open for the life of the process.
  - **An empty or relative `pw_dir` is no home.** `Path("")` is `.`, which would make the working directory a home and refuse a project's own `.npmrc`.
  - **The cheap key compares the passwd home's cached value and never stats it.** The full key reads its store links, and a build covers it. Stat'ing it on every call would hang every check when it sits on a dead mount. The trade-off is a documented limit: a store below the passwd home (when that isn't `$HOME`) relinked while the server runs is matched at its new target at the next rebuild, a change in `$HOME`'s store directories, or after a restart. Paths spelled through the store are refused all along. A recovered lookup changes the cached value and so the cheap key, so the stores are rebuilt at once.
- **`HOME=/`** (pre-existing from #1028, found in the review). `"/".rstrip("/")` is empty, so the cheap key stat'ed `""` and saw nothing. `_under` joins paths below a home correctly for `/`.
- **Out of scope, documented:**
  - **Other users' store links** (`/home/bob/.ssh -> /data/bob`). They stay matched by spelling only: finding them would mean reading every user's home on each rebuild, and keying on every home's links.
  - **A home root relinked after start-up** is seen after a restart (resolved once per process).
  - **One user's home that is itself a link** (`/home/bob2 -> /data/bob2`), when it isn't the server's own: the walker reaches `/data/bob2/.ssh`, but results are still refused by their spelled form.

**Anchor:** `pyeye.validation._resolved_home_roots` / `_passwd_home` / `_homes`; `tests/test_credential_home_roots.py`; #1030.

**Applies-to:**

- `pyeye.validation._build_credential_stores`, `pyeye.validation._StoreCache` (its keys `_dir_key` and `_store_key`), and through them `credential_path`, `restricted_reason`, `restricted_dir`, `pyeye.async_utils.pruned_walk` and `pyeye.resolver.restricted_path`;
- `SECURITY.md` (the credential-store paragraph and its limits).

**Verify:** gold. `uv run pytest tests/test_credential_home_roots.py tests/test_restricted_any_form.py` passes. It checks:

- a store at a symlinked root's resolved form is refused and pruned, and a walk through the link skips it;
- a root is resolved once across rebuilds and never under the store lock; a failed resolve logs, keeps the spelling and is retried; a root resolving to `/` adds nothing; `HOME=/` still has a cheap key;
- a failed passwd lookup is retried after the backoff rather than cached, and a success is kept; an empty or relative `pw_dir` is no home; a recovered lookup rebuilds the stores;
- a single-home root resolves as one home;
- every `USER_HOMES` pattern reads as a root;
- the passwd home's linked store is refused at its target, and its stores are refused by spelling. A relink below it is seen at the next rebuild (pinned limit), and the cheap key never stats it;
- another user's store link is pinned as matched by spelling only.
