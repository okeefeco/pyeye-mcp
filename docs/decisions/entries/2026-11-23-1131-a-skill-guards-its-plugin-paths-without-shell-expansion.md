---
date: "2026-11-23"
title: "A shipped skill guards its plugin paths with a test, not ${VAR:?} (#1131)"
issues: [1131]
anchors: ["skills/decision-log/SKILL.md", "skills/duplication-review/SKILL.md", "tests/test_skill_plugin_guard.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — A shipped skill guards its plugin paths with a test, not ${VAR:?} (#1131)

**Friction:** explorer's shipped-skills audit (on Poetry 2.5.2) copied a skill's plugin command out of context. `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PLUGIN_DATA}` were empty, and it failed as `/.venv: Permission denied`. The issue proposed `${VAR:?hint}`. Claude Code's plugin reference documents only the plain `${NAME}` form as substituted into skill text, and says the variables "aren't present in the environment of commands Claude runs through the Bash tool". A `${VAR:?hint}` form would probably not be substituted, so the shell would find the variable unset and fail even inside the plugin: it would break the working path to fix the broken one.

**Decision:** assigned by coordinator-3 (2026-11-23) as #1131's polish.

- Each plugin command keeps the plain `"${CLAUDE_PLUGIN_ROOT}"` / `"${CLAUDE_PLUGIN_DATA}"` form and starts with `[ -n "${CLAUDE_PLUGIN_ROOT}" ] && [ -n "${CLAUDE_PLUGIN_DATA}" ] || { echo "<hint>" >&2; false; } &&`. Substituted, the test is true and `uv` runs. Copied out of the plugin, both are empty: it prints the hint and `uv` never runs.
- `false`, not `exit`, so a command pasted into an interactive shell doesn't close it.
- No shell parameter-expansion form (`${CLAUDE_PLUGIN_…:?…}`, `:-`, `#`, `%`, `/`) is used in a skill.

**Anchor:** `skills/decision-log/SKILL.md` and `skills/duplication-review/SKILL.md` (their plugin command blocks); `tests/test_skill_plugin_guard.py`; #1131.

**Applies-to:**

- Every registered skill page whose text uses `${CLAUDE_PLUGIN_ROOT}` or `${CLAUDE_PLUGIN_DATA}`: today `decision-log` and `duplication-review`. `architecture-review` doesn't use them yet; its runnability for plugin users is #1132.

**Verify:** PARTIAL — gold: `uv run pytest tests/test_skill_plugin_guard.py` passes. It sweeps every registered skill page (`DOCS`, kind `skill`) that uses the variables, and for each checks that only the plain form is used, that the unsubstituted command fails with the hint without running `uv`, and that the substituted command runs `uv` with the plugin's paths. Unverifiable here: Claude Code's substitution itself; the test simulates it as textual replacement of `${NAME}`, which is what the plugin reference describes.
