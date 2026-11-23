---
date: "2026-11-23"
title: "A decision's sites resolve through pyeye to canonical handles; an unresolved site keeps its reason (#1178)"
issues: [1178, 1182, 1132]
anchors: ["pyeye.decision_sites.refs", "pyeye.decision_sites.resolve_sites", "pyeye.decision_sites.pyeye_resolver", "tests/test_decision_sites.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — A decision's sites resolve through pyeye to canonical handles; an unresolved site keeps its reason (#1178)

**Friction:** two pieces of work need to turn a decision entry's `Applies-to` and `Anchor` references into code sites.

- The architecture-review engine (#1178, R3/R5 of #1132's design) matches them to an area's module globs.
- `decisions check` (#1182) fails on stale ones.

Matching the text alone would let a re-exported path (`pkg.Thing`) miss the area its definition lives in, and would treat a stale reference as merely "not in this area". The open question was whether to resolve through pyeye. The user ruled (2026-11-23): dogfood pyeye.

**Decision:** assigned by coordinator-3 (2026-11-23), on the user's ruling.

- **One shared helper, `pyeye.decision_sites`,** used by both. It lives beside `pyeye.decisions`, which stays standard-library only so CI can run `scripts/decisions.py` with a bare Python.
- **What a reference is** (`refs`): a backticked dotted name of two or more parts (`handle`), or a `.py`/`.pyi` path (`path`), with a pytest `::node` trimmed to its file and `()` dropped. Each carries its line.
- **Not references:**
  - `none (<why>)` and prose such as "every edge in `REGISTRY`";
  - config files and version pins;
  - a single bare word: it would resolve by guesswork to any same-named definition.
- **Resolution** (`resolve_sites`, `pyeye_resolver`) goes through pyeye's own `resolve`, so a re-export collapses to the definition site's canonical handle and a file path gives its module. A caller matches canonical handles, never the text as written.
- **Never a silent drop:** a reference that isn't exactly one project definition keeps its `reason`. The reasons are `unresolved`, `ambiguous`, `external`, `file_not_found` and `no_symbol_at_position`. Each caller reports it: the engine as a packet note, `decisions check` as a failure.
- **Static** (C19): nothing of the analysed project is imported or run. The analyzer is built only on the first question.
- **Rejected:** textual matching only, which misses re-exports and hides stale sites; and a second resolver per caller.

**Anchor:** `pyeye.decision_sites.refs`, `pyeye.decision_sites.resolve_sites`, `pyeye.decision_sites.pyeye_resolver`; `tests/test_decision_sites.py`; #1178, #1182.

**Applies-to:**

- every caller that turns a decision entry's references into code sites: the architecture-review engine's area matching (#1178) and `decisions check`'s stale-reference check (#1182). Neither has its own resolver: both go through `pyeye.decision_sites`.

**Verify:** gold. `uv run pytest tests/test_decision_sites.py` passes. It checks:

- which spans are references, with their kinds and lines;
- that a re-exported path resolves to its definition site and a file path to its module;
- that an unknown name and an external name come back with their reasons;
- that the analyzer is lazy.
