---
date: "2026-11-23"
title: "The plugin's venv is keyed on the plugin root, and the server syncs it before it starts (#1136)"
issues: [1136, 600]
anchors: ["scripts.plugin_runtime.slot_dir", "scripts.plugin_runtime.ensure", "scripts.plugin_runtime.guard_message", ".claude-plugin/plugin.json", "hooks/hooks.json"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — The plugin's venv is keyed on the plugin root, and the server syncs it before it starts (#1136)

**Friction:** `claude --plugin-dir <worktree>` couldn't develop the shipped plugin. The repo-root `.mcp.json` was taken as the plugin's top, so the dev config launched and never connected. Every `--plugin-dir` session is `pyeye@inline` and shares one `${CLAUDE_PLUGIN_DATA}`, so the single `.venv` there held an editable install of whichever checkout synced first: parallel worktrees ran each other's code. And the server started with `--no-sync` while the async setup hook was still building that venv, so a fresh data dir failed the first session.
**Decision:** Remove `.mcp.json`; the plugin is the dev setup. Every plugin-run Python goes through `scripts/plugin_runtime.py` (stdlib only, `uv run --no-project`): the venv is `${CLAUDE_PLUGIN_DATA}/venvs/<sha256 of the real plugin root>/.venv`, synced with `uv sync --no-dev --frozen` whenever it is missing or its `uv.lock` copy differs, by the server launcher itself (synchronously, output on stderr) as well as the setup hook. Rejected: the checkout's own `.venv` for a dev checkout. A `--no-dev` sync would strip its dev tools, and a special case for "dev" would make normal installs and dev mode differ. A synchronous guard hook warns in the pyeye repo when the running plugin isn't the session's checkout.
**Anchor:** `scripts.plugin_runtime.slot_dir`, `scripts.plugin_runtime.ensure`, `scripts.plugin_runtime.guard_message`; the `pyeye` server in `.claude-plugin/plugin.json`; `hooks/hooks.json`; #1136, #600.
**Applies-to:** every way the plugin runs pyeye code: the MCP server (`launch` mode), the SessionStart setup hook (`setup`), and the shipped skills that run a pyeye module (`decision-log`, `duplication-review`, through `python` mode). Nothing may name `${CLAUDE_PLUGIN_DATA}/.venv` or start against a venv nobody filled (#600).
**Verify:** gold. `tests/test_mcp_launch_config.py` asserts there is no `.mcp.json`, that the server and both hooks run `plugin_runtime.py`, that no shipped `skills/*/SKILL.md` names the old venv, and (integration) that two fresh worktrees sharing one data dir each import `pyeye` from their own `src/`. `tests/test_plugin_runtime.py` covers staleness, resync after failure, pruning and the guard.
