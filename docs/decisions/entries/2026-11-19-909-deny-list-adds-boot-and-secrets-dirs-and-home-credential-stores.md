---
date: "2026-11-19"
title: "The deny-list adds boot and secrets dirs, and credential stores below every user home (#909)"
issues: [909, 939, 856, 867]
anchors: ["pyeye.validation.PathValidator.RESTRICTED_TARGETS", "pyeye.validation.PathValidator.CREDENTIAL_PATHS", "pyeye.validation.PathValidator.USER_HOMES", "pyeye.validation.credential_path", "pyeye.validation.restricted_dir", "tests/test_extended_deny_list.py"]
status: "active"
amends: ["2026-11-18-856-every-caller-path-is-checked-in-its-final-form.md", "2026-11-18-939-the-deny-list-is-anchored-patterns-only-matched-ignoring-case.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-19 — The deny-list adds boot and secrets dirs, and credential stores below every user home (#909)

**Friction:** found by the #901 security review and diagnosed in #909. Credential stores (`~/.ssh`, `~/.aws`, `~/.config/gcloud`, `~/.netrc`…) and `/boot`, `/run/secrets` and `/var/root` passed every check. `.ssh` and `.aws` only logged a warning (`DANGEROUS_NAMES`).

**Decision:** the maintainer's ruling of 2026-11-18 (via coordinator-3). It is `security`, not breaking.

- **SYSTEM dirs, anchored like `/etc`:** `^/boot/`, `^/run/secrets/`, `^/var/run/secrets/` (Kubernetes service-account tokens), `^/var/root/` and `^/private/var/root/` (macOS root's home and its resolved form).
  - They are refused, pruned in walks, and they define ancestors. `/run`, `/var`, `/var/run` and `/private/var` join `/` and `/private` as refused scan roots (#856 ruling).
  - `/var/lib` stays out, because Jenkins workspaces and Docker volumes live there.
- **CREDENTIAL stores** (`PathValidator.CREDENTIAL_PATHS`: `.ssh`, `.aws`, `.gnupg`, `.config/gcloud`, `.azure`, `.kube`, `.docker`, `.config/gh`, `.netrc`, `.pypirc`, `.pgpass`, `.git-credentials`, `.npmrc`):
  - **What is refused:** the store itself, or anything in it, when it sits directly below any user home. It is matched on every checked form, ignoring case (`validation.credential_path`).
  - **Refused and pruned, but no ancestors:** a scan of `~`, `/home` or `/Users` still works and skips the stores.
  - **Projects inside a store:** a project placed inside one (`~/.config/gh/x`) is refused, as intended.
- **User homes are matched by pattern, never enumerated** (`PathValidator.USER_HOMES`: `^/home/[^/]+/`, `^/Users/[^/]+/`, `^/root/`).
  - **The server's own home:** `Path.home()` is added and read once per process (`functools.cache` on `_credential_pattern`).
  - **Later homes:** a home created after the server started is covered, and nothing can go stale.
  - **Limit:** a `$HOME` outside those roots (e.g. `/var/lib/jenkins`) is covered only for the server's own user. The coordinator approved this design over enumerating homes.
- **The walk prune follows** (`restricted_dir`): it also skips credential stores, and it now ignores case like the target check (#939).
- **`DANGEROUS_NAMES` stays warn-only.**
- **Docs facts:** `security.path_checks` lists the credential stores and the home patterns. A new `security.path_checks.ancestors` fact replaces SECURITY.md's hand-written ancestor list, which this change made stale.
- **Scope:** Windows stays out of scope (#867).

**Anchor:** maintainer ruling of 2026-11-18 (via coordinator-3); `pyeye.validation.PathValidator.RESTRICTED_TARGETS`, `CREDENTIAL_PATHS`, `USER_HOMES`; `pyeye.validation.credential_path`, `_credential_pattern`, `restricted_dir`; `SECURITY.md`; #909, #939, #856.
**Applies-to:**

- the lists: `pyeye.validation.PathValidator.RESTRICTED_TARGETS`, `pyeye.validation.PathValidator.CREDENTIAL_PATHS`, `pyeye.validation.PathValidator.USER_HOMES`;
- the checks: `pyeye.validation.PathValidator._check_targets`, `pyeye.validation.credential_path`, `pyeye.validation._credential_pattern`, `pyeye.validation.restricted_dir`;
- the facts: `pyeye.docs_facts.extractors.security._path_checks`.

**Verify:** gold. `uv run pytest tests/test_extended_deny_list.py` passes on POSIX. It checks:

- the system dirs (any case) are refused, and their neighbours (`/var/lib/jenkins`, `/var/www`, `/run/user`) pass;
- `/run`, `/var`, `/var/run` and `/private/var` are refused as scan roots;
- every credential store is refused and pruned below `/home/<u>`, `/Users/<u>` and `/root`, in any case;
- look-alikes pass: a project's own `.ssh` fixture, `.sshx`, `/srv/.ssh`;
- a project inside a store is refused;
- `~`, `/home` and `/Users` are not refused ancestors;
- a home created later is covered;
- a `$HOME` outside the roots is covered for its own user only;
- a symlink into a store is refused;
- walking a home skips its stores.
