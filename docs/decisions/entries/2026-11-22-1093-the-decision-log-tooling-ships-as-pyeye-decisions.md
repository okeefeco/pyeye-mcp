---
date: "2026-11-22"
title: "The decision-log tooling ships as pyeye.decisions; this repo's script wraps it (#1093)"
issues: [1093, 679, 636, 1083, 495]
anchors: ["pyeye.decisions.main", "pyeye.decisions.check", "pyeye.decisions.DEFAULT_GRANDFATHERED", "scripts/decisions.py", "skills/decision-log/SKILL.md"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-22 — The decision-log tooling ships as pyeye.decisions; this repo's script wraps it (#1093)

**Friction:** the shipped `decision-log` skill told agents to run `python scripts/decisions.py index` / `check` "if the repo has it". Only this repository had it, so every other repo using the plugin got the skill without its tooling: no index, no `Applies-to` check, no amend/supersede link validation. It was also a drift risk (#629): this repo's checks and what users get could diverge.

**Decision:** coordinator-3's assignment of #1093 (user-scheduled), following the `pyeye.duplication` pattern (#495).

- **The engine is `pyeye.decisions`**, runnable as `python -m pyeye.decisions index|check|migrate`.
  - Its settings are the `main` keyword arguments: the log directory (default `docs/decisions` under the working directory), the grandfather list (default none), the `migrate` header, and the command its messages name.
  - `--decisions-dir` and a repeatable `--grandfathered` set the first two from the command line.
  - A repo with no log answers "no entries", exit 0, for `index` and `check`.
- **`scripts/decisions.py` is a thin wrapper.** It holds what is this repo's alone: `APPLIES_TO_GRANDFATHERED` (#636, only shrinks), the `DECISIONS.md` header, and `COMMAND`.
  - So pre-commit, CI and the `.claude/instructions` references keep the same command.
  - Its output is byte-identical to the old script's on this repo (`check` and five `index` forms, compared on one tree).
- **Stdlib only, loaded by path.** CI runs the check with a bare `python` (no project installed), and importing the `pyeye` package needs `parso`. So the wrapper loads `src/pyeye/decisions.py` by file path, and the module has no relative or third-party imports. A test enforces this, and runs the wrapper with `python -I -S`.
- **The skill runs the shipped module**, through the plugin's `uv run --project "${CLAUDE_PLUGIN_ROOT}"` form, as `duplication-review` does.

**Anchor:** `pyeye.decisions.main`; `scripts/decisions.py`; `skills/decision-log/SKILL.md`; #1093.

**Applies-to:** `pyeye.decisions` (`main`, `load`, `check`, `stale_grandfathered`, `migrate`); `scripts/decisions.py`; `skills/decision-log/SKILL.md`; the `decisions-check` pre-commit hook and CI's "Validate decision log" step.

**Verify:** gold. `uv run pytest tests/test_decisions_module.py tests/test_decisions_script.py` passes. It checks:

- the wrapper's output equals the module's with the wrapper's settings, for `check` and three `index` forms;
- the wrapper runs with a bare `python -I -S`;
- the module imports only the standard library;
- a repo with no log gets "no entries";
- `--decisions-dir` and `--grandfathered` work, and nothing is grandfathered by default;
- the skill names the plugin command form and only subcommands and flags that exist.
