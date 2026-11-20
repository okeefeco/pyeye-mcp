---
date: "2026-11-20"
title: "A result is refused when any form of its file is restricted, and a credential store that is a link is matched at its target (#1019)"
issues: [1019, 999, 909, 1005, 856, 1016]
anchors: ["pyeye.validation.restricted_reason", "pyeye.validation.credential_path", "pyeye.validation._credential_pattern", "pyeye.validation._StoreCache", "pyeye.validation._store_key", "pyeye.validation.restricted_dir", "pyeye.resolver.restricted_path", "tests/test_restricted_any_form.py", "tests/test_restricted_path_windows.py"]
status: "amended"
amends: ["2026-11-20-999-results-resolving-into-a-restricted-directory-are-refused.md", "2026-11-19-909-deny-list-adds-boot-and-secrets-dirs-and-home-credential-stores.md"]
supersedes: []
amended_by: ["2026-11-20-1030-home-roots-resolve-and-the-passwd-home-counts.md"]
superseded_by: []
---

## 2026-11-20 — A result is refused when any form of its file is restricted, and a credential store that is a link is matched at its target (#1019)

**Friction:** on #1016's Windows 3.11 leg, `TestOnWindows::test_the_servers_own_credential_store_is_refused` returned False for `C:/Users/runneradmin/.ssh/id_rsa`. It took 230 ms there and 2.4 ms when it passed on #1008, with the same interpreter. Test order rules out the `_credential_pattern` cache: `home_at`'s teardown cleared it, and the test just before rebuilt it under the real home. So the runner's `~\.ssh` resolved by another route. The log doesn't say what the resolve returned. Reading the code showed two real gaps behind any such route. `restricted_path` (#999) checked only the RESOLVED form, while `validate_final` (#856) checks every form of an input. And the store match (#909) knew a store only by its spelling below a home, so a store that is itself a link (`~/.ssh -> /data/keys`) was missed at its target, by the results check and by the walkers' `restricted_dir` prune alike.

**Decision:** ruled by coordinator-3 (2026-11-20) as within the approved #999 policy: refuse anything in a restricted directory, with no new key or reason.

- **One predicate.** `validation.restricted_reason(form)`: the form is, or is inside, a `_RESTRICTED_DIRS` directory (the literals of the anchored `RESTRICTED_TARGETS`, case ignored; the reason is its pattern) or a credential store (`credential_path`). `PathValidator._check_targets` (inputs), `restricted_dir` (the walkers) and `resolver.restricted_path` (results) all apply it. `_check_targets` used to `re.search` each pattern, which is equivalent while every pattern is an anchored literal (#939). Tests stand in a restricted directory by patching `_RESTRICTED_DIRS`, so the one input test that patched `RESTRICTED_TARGETS` now patches that.
- **Any form, for results too.** `restricted_path` checks the path as spelled (`path_utils.absolute_path`: absolute, `..` collapsed, links kept) and then resolved, refusing if either is restricted, as `validate_final` does. The fail-closed rules are unchanged (#999, #1005): the spelled check comes first, so a path spelled inside a store is refused even when its resolve fails.
- **A store that is a link.** `_credential_pattern` also records, for each store below the server's own home, its resolved location when that differs from the resolved home plus the store. `credential_path` matches a form at or inside that location (case ignored) as that store. Other users' homes are matched by spelling only, as before (#909).
- **The store cache is keyed (review of #1028).** `_credential_pattern` is a `_StoreCache`, no longer a `functools.cache`. A build is served only for the key it was built from: the home's spelling plus the `readlink` of the home and of every store and store parent below it (`_STORE_LINK_PATHS`, e.g. `.config` for `.config/gcloud`). The build runs under a lock. Two bugs this closes:
  - **A race:** a catch-up sweep on a background thread could store a build made under the real home after a test had patched its home and cleared the cache. That made the end-to-end test flaky. It wasn't a production leak, since the home is fixed per process.
  - **A real gap:** a store linked or repointed after the first build (`~/.gnupg -> <tmp>/gpg`, a profile switcher relinking `~/.aws`) went unseen until a restart.

  `tests/conftest.py` also cancels every `ProjectManager` catch-up timer after each test, so no background sweep crosses into the next.
- **Cost, kept small.** The full key costs ~130 µs (a `readlink` per path, each raising for a missing store). Checked per walk entry, it slowed a django `filtered_rglob` walk from 4.0 s to 6.0 s. Two measures make it cheap:
  - **A cheap key first:** `_dir_key` is the home's spelling plus the mtime and (POSIX) ctime of the two directories the stores sit in (`~`, `~/.config`; `_STORE_LINK_DIRS`), which costs two `stat` calls. Making, removing or repointing a link changes its directory's times. A change within the same tick as an earlier one can't be seen that way. So the cheap key is trusted only for a **vouched** build: one whose key was read when both directories' latest times were already 2 s old (`_RECENT_NS`; FAT has 2 s ticks). Any later change then lands in a later tick. Until a full-key match is made once the directories are that old, every call checks the full key. The first version compared the times with *now*. On a filesystem with 1 s timestamps (HFS+, ext3, many NFS servers), relink, build, relink in the same second, then 2 s idle, let the stale build be trusted indefinitely (final review of #1028; `test_a_build_inside_a_changing_tick_is_not_trusted_later`, which floors the times and fakes the clock). The ctime is what defeats `touch -d`: setting the mtime back to exactly the old value still moves the ctime, which `os.utime` can't set. Windows has no change time (`st_ctime` is the creation time there), so it keys on mtime alone.
  - **One snapshot per batch:** `credential_stores()` is taken once and passed to `restricted_reason` / `restricted_dir` / `credential_path`, once per walk (`async_utils.pruned_walk`) and once per path's forms (`restricted_path`, `_check_targets`). A store relinked mid-walk is seen by the next walk.

  **Covered:** a store's own link made, removed or repointed, directly in `~` or in `~/.config` (`.config/gcloud`, `.config/gh`), or `~/.config` itself relinked; the same followed by `touch -d` restoring the old mtime (POSIX); two relinks in one timestamp tick around a build, on filesystems with coarse timestamps. **Documented limits** (SECURITY.md): a store that links to a second link outside `~` and `~/.config` whose target is repointed. Nothing watched changes there, and the full key reads only the store's own link, so the old target holds until `~` or `~/.config` next changes or a restart. Paths spelled through the store are still refused by their spelling. Also, on Windows, a relink followed by restoring the exact old mtime. And a store directory on a filesystem whose clock runs more than 2 s behind the server's (NFS skew): a time that looks settled can still share its tick with a further change. The second-hop limit was there before this rework too; covering it would take a full resolve of every store on each check, the cost this rework removes.

  Measured on dev01 against a cache with no checks: the django walk's extra time over five runs ranged from −22 to +357 ms, median ≈ +60 ms on ~3.3–3.9 s, so within noise under shared load; `restricted_path` went from ~140 to ~200–220 µs per call.
- **Diagnostics.** The Windows test's assertion reports what `restricted_path` saw (the strict and non-strict resolves, the home, the pattern and linked stores), so a recurrence explains itself.

**Anchor:** `pyeye.validation.restricted_reason` / `credential_path` / `_credential_pattern`; `pyeye.resolver.restricted_path`; `tests/test_restricted_any_form.py`; #1019.

**Applies-to:**

- `pyeye.validation.restricted_reason`, `pyeye.validation.PathValidator._check_targets` and every input check built on it (`validate_path`, `validate_final`, `validate_scan_root`);
- `pyeye.validation.restricted_dir` and the walkers that prune with it (`pyeye.async_utils.pruned_walk`, one `pyeye.validation.credential_stores` snapshot per walk);
- `pyeye.validation.credential_path`, `pyeye.validation._credential_pattern` (a `pyeye.validation._StoreCache`) and `pyeye.validation._store_key`;
- `tests/conftest.py`'s `_no_catchup_sweeps_across_tests`;
- `pyeye.resolver.restricted_path`, and through it `pyeye.resolver.in_restricted_dir` and every result site #999 lists;
- `SECURITY.md` (the results and credential-store paragraphs).

**Verify:** gold — `uv run pytest tests/test_restricted_any_form.py tests/test_restricted_path_windows.py` passes. It checks:

- a store that is a symlink is matched at its target (`credential_path`, `restricted_path`, the walkers' `restricted_dir`), a sibling of the target isn't, and a project symlink into the target is refused through `resolve`;
- a path spelled inside a store that resolves outside is refused, a link into a store still is, and a symlinked project root still passes;
- `validate_final` and `restricted_path` refuse exactly the same paths;
- a build for another home is never served, nor a stale build stored after a clear (the deterministic race proof); a store linked, repointed, or reached through a relinked parent after the first build is seen; an mtime restored with `touch -d` after a relink is still seen; the cheap key serves an old, unchanged home without the full check; the second-hop limit is pinned; and the conftest helper cancels pending catch-up sweeps and nothing else (`tests/test_catchup_sweeps_cancelled.py`);
- every `RESTRICTED_TARGETS` pattern is `^` + a literal directory + `/`, one-to-one with `_RESTRICTED_DIRS`, so none silently stops applying;
- on Windows, a store that is a junction is refused at its target, and the real-home test says what it saw when it fails.
