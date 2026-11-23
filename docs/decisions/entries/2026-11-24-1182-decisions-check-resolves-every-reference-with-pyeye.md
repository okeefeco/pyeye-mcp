---
date: "2026-11-24"
title: "decisions check --resolve resolves every Anchor and Applies-to reference with pyeye, in CI (#1182)"
issues: [1182, 1178, 636, 679, 1093]
anchors: ["pyeye.decision_check.resolve_check", "pyeye.decision_check.ResolveReport", "pyeye.decisions.main", "pyeye.decisions._resolve", "scripts/decisions.py", "tests/test_decision_check.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-24 — decisions check --resolve resolves every Anchor and Applies-to reference with pyeye, in CI (#1182)

**Friction:** a decision names the code its rule governs in `**Anchor:**` and `**Applies-to:**`, but `decisions check` validated only the format. A rename or a deletion left a decision governing nothing, with no warning. The first resolving run over this repo found 21 such references in 12 of the 123 active entries. The maintainer's direction (2026-11-23): dogfood pyeye in the decision log.

**Decision:** assigned by coordinator-3 (2026-11-24), agreed with designer.

- **What is checked:** the references in the `Anchor` and `Applies-to` fields of ACTIVE entries. Superseded and amended entries are history, and their references may go stale. References are classified from the layout by `pyeye.decision_sites` (#1188's entry):
  - a project `handle` must resolve through pyeye (a re-export to its definition site);
  - a repo path with a `/` must exist;
  - either one failing is a problem, ``entry:line: <field> `<ref>` ...``;
  - an `external` that doesn't resolve is listed on every run, never a failure.
- **Short forms** (`JediAnalyzer.find_importers`, a bare `server.py`) can't be checked without a guess.
  - They fail in an entry dated on or after the gate date, `SHORT_FORMS_FAIL_FROM` in `scripts/decisions.py`: **2026-11-24**, the day this landed.
  - Older ones are counted on every run, like the other allow-lists: 115 when this landed.
  - The shipped module has no gate by default (`short_forms_fail_from=None`), so a repo adopting it opts in.
- **Where it runs:** CI only.
  - Measured on dev01: the 121 active entries' 671 handle references (476 unique) took 22.6 s in one cold process, and the whole `check --resolve` took 26.6 s and about 250 MB. That is too slow for every commit.
  - It is a step in CI's `changelog-validation` job, which runs on every event, so a PR adding only an entry is checked, and which already reports on `merge_group`.
  - Pre-commit keeps the format-only `check`.
- **Never a silent pass:** `pyeye.decisions` stays standard-library only and imports `pyeye.decision_check` by name only for `--resolve`. Without pyeye, `--resolve` is a problem, never a pass.
- **The 21 found** are carried forward by the amending entry `2026-11-24-1182-anchors-that-drifted-...`. Old bodies are not rewritten.
- **Rejected:**
  - pre-commit, too slow;
  - checking every entry, which would fail on history;
  - resolving short forms by their last segment, which is a guess.

**Anchor:** `pyeye.decision_check.resolve_check`, `pyeye.decisions.main` (`check --resolve`, `--project-root`), `scripts/decisions.py` (`SHORT_FORMS_FAIL_FROM`); `tests/test_decision_check.py`; #1182.

**Applies-to:**

- the check: `pyeye.decision_check.resolve_check`, `pyeye.decision_check.ResolveReport`, called from `pyeye.decisions.main` through `pyeye.decisions._resolve`;
- this repo's settings, `scripts/decisions.py` (`SHORT_FORMS_FAIL_FROM`, the project root), run by CI's `changelog-validation` job in `.github/workflows/ci.yml`;
- the shared classification it builds on, `pyeye.decision_sites.resolve_sites`.

**Verify:** gold.

- `uv run pytest tests/test_decision_check.py` passes. It checks that:
  - resolving references pass, re-exports included;
  - a removed handle or file fails with `entry:line`, and prose outside the two fields isn't read;
  - amended entries are skipped;
  - an old short form is counted and a gated one fails;
  - an unresolved external is listed, not failed;
  - the count prints on every run;
  - plain `check` doesn't resolve, and `--resolve` without pyeye fails;
  - the wrapper's gate is 2026-11-24.
- `uv run python scripts/decisions.py check --resolve` passes on this repo.
