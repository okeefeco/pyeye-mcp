---
date: "2026-11-23"
title: "In pyeye's repository every session runs its checkout's server and skills; the plugin ships four skills by path (#1147)"
issues: [1147, 1136, 600]
anchors: [".mcp.json", ".claude/settings.json", ".claude-plugin/plugin.json", "scripts.plugin_runtime.main"]
status: "active"
amends: ["2026-11-23-1136-one-plugin-venv-per-plugin-root.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — In pyeye's repository every session runs its checkout's server and skills; the plugin ships four skills by path (#1147)

**Friction:** #1136 made `claude --plugin-dir <worktree>` the dev setup, but remote sessions can't be given `--plugin-dir`, so they ran the installed plugin, not their worktree. The project-settings marketplace route can't fix that: Claude Code keys a marketplace by its manifest name (the repo's is `pyeye-marketplace`, the same as the user's GitHub one) in a global registry, one path per name, and a plugin source must start with `./`.
**Decision:** The repo serves its own checkout without the plugin. `.mcp.json` is restored (#600's `uv run --project ${CLAUDE_PROJECT_DIR:-.} --frozen`). The four shipped skills live in `.claude/skills/` (project skills here), and `plugin.json` lists exactly those four by path, so the repo-internal skills beside them never ship. `.claude/settings.json` disables `pyeye@pyeye-marketplace` here and enables the `.mcp.json` server. Skills that run a pyeye module fall back to the checkout's environment when `${CLAUDE_PLUGIN_ROOT}` isn't substituted. The plugin as shipped is tested with `--plugin-dir <clone>` from another directory, since inside the repo it duplicates every tool and skill. The guard hook is removed. #1136's one venv per plugin root stays.
**Anchor:** `.mcp.json`; `.claude/settings.json` `enabledPlugins` / `enabledMcpjsonServers`; `.claude-plugin/plugin.json` `skills`; `scripts.plugin_runtime.main`; #1147, #1136, #600.
**Applies-to:** every shipped skill (`SHIPPED_SKILLS` in `tests/test_mcp_launch_config.py`: `architecture-review`, `decision-log`, `duplication-review`, `python-explore`) and every pyeye-module runner block in them (today `decision-log` and `duplication-review`); the repo's `.mcp.json` and `.claude/settings.json`; `plugin.json`'s `skills`.
**Verify:** gold. `tests/test_mcp_launch_config.py` asserts the `.mcp.json` launch (#600), the settings, `plugin.json`'s exact skill list, no top-level `skills/`, only the setup hook, and that every runner block in every shipped skill has both branches. Integration runs the `.mcp.json` launch and the `decision-log` runner in both modes in a fresh worktree. Unverifiable here: that a restarted remote session picks the settings up.
