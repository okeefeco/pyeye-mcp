<!--
Audience: Claude Code
Purpose: Session startup and working-directory expectations
When to update: When startup or worktree conventions change
-->

# Session Startup

## Where to start

Start in the main repo checkout (`/home/mark/GitHub/pyeye-mcp`) or in an existing worktree. There is no special "hub" worktree — Claude configuration (`.claude/`, `CLAUDE.md`) is read from whichever checkout you start in.

## Isolated workspaces (worktrees)

For feature work that needs isolation, create a worktree via native tooling — the superpowers `using-git-worktrees` skill (which uses `EnterWorktree`). Worktrees live under `.claude/worktrees` (gitignored) and the harness manages their lifecycle. Set up each worktree's environment with `uv sync` (installs main + the default `dev` group; add `--group docs` only when building docs). See `04-agent-triggers.md` → Worktrees for the full trigger map.

## Working directory

The harness persists the working directory between Bash calls. Prefer absolute paths for clarity, but no manual `CLAUDE_WORKING_DIR` bookkeeping is needed.

## Context-loss recovery

If context is lost:

1. Check the GitHub issue — `gh issue view <number>` (the branch name carries the issue number).
2. Your TodoWrite list persists across resets.
3. Inspect git state — `git status`, `git log --oneline -5`, `git diff`.
4. Resume from your todo list.
