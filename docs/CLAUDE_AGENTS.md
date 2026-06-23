# Claude Code Agents for PyEye

This document describes the Claude Code agents (subagents) used in this repository.

## Overview

Agents appear in Claude Code's `/agents` command and run in a separate context from your main session, so detailed analysis doesn't clutter the main conversation. Each agent is defined by a markdown file in `.claude/agents/` with YAML frontmatter that sets its name, description, and the tools it may use.

## Available agents

### smart-commit

Git commit workflow with pre-commit validation: checks status/diff, screens for secrets, runs the pre-commit hooks, writes a conventional-commit message, and handles hook fixes. Invoke when the user says "commit". See `.claude/instructions/06-workflow-commits.md`.

### general-purpose

Catch-all for complex, multi-step research and search tasks that span many files. Use when you need a conclusion synthesised from a broad sweep rather than a single lookup.

> Other entries in `/agents` (e.g. `statusline-setup`) are Claude Code built-ins, not defined in this repository.

### Retired agents

- **cross-platform-validator** (retired #483) — it was built on the Jedi-shaped tools removed in v2.0 (`find_symbol`, `get_type_info`, `find_imports`, `get_module_info`, `list_modules`) plus deprecated `find_references` / `get_call_hierarchy`, and its core job (finding code matching a *pattern* like `str(path)`) is a textual search that pyeye is explicitly not for. Use `scripts/check_cross_platform_paths.py` and the rules in `.claude/instructions/10-cross-platform.md` instead.
- **worktree-manager** (retired #362) — superseded by native worktree tooling (`EnterWorktree` / the `using-git-worktrees` skill).

## How agents work

1. **Separate context** — agents run isolated, preserving the main session.
2. **Tool restrictions** — the frontmatter `tools:` line is an allow-list; an agent can only call those tools. Grant the minimum needed.
3. **Definition format**:

   ```markdown
   ---
   name: agent-name
   description: "Brief description of what the agent does"
   tools: tool1, tool2, tool3
   ---

   [Agent system prompt with detailed instructions]
   ```

## Creating a new agent

1. **Pick the right tools for the task.** This is the lesson from the retired
   cross-platform-validator: match the tool to the job, don't force everything
   through one layer.
   - **Semantic navigation** (what is this symbol, what does it call, who imports
     it, what's the structure) → the pyeye primitives `resolve` / `resolve_at` /
     `inspect` / `outline` / `expand` / `trace`. See the `python-explore` skill.
   - **Textual / pattern search** (find every site that does `str(path)`, grep a
     regex, locate a string literal) → `Bash`/grep. pyeye is not a content search
     engine and does not answer "who references this" (deferred to #333).
   - **Editing** → `Read` then `Edit`/`MultiEdit`.
2. **Define the agent** in `.claude/agents/<name>.md` with the frontmatter above,
   granting only the tools it needs.
3. **Test it** via `/agents` or a direct `Task(subagent_type="<name>", …)` call,
   and document it in this file.

## Benefits

- **Context preservation** — heavy analysis stays out of the main session.
- **Tool safety** — agents only hold the permissions they're granted.
- **Reusability** — agent definitions are checked in and shared across the team.
