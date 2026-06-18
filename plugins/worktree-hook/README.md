# worktree-hook

A Claude Code plugin that augments the native `EnterWorktree`/`ExitWorktree`
tools with a matched pair of hooks — `WorktreeCreate` (custom directory/branch
naming) and `WorktreeRemove` (clean teardown). Installed separately from the
`pyeye` MCP plugin but managed in the same marketplace.

## What it does

When Claude Code creates a worktree, this hook takes over directory and branch
naming:

- **Nested naming model** — the leading type prefix becomes its own directory
  level; branch and directory share the same nested form. The name is split at
  its first separator (`/` or `-`):

  | Requested name | Branch | Worktree dir |
  | --- | --- | --- |
  | `feat-361-desc` | `feat/361-desc` | `feat/361-desc/` |
  | `feature/361-desc` | `feat/361-desc` | `feat/361-desc/` |
  | `bugfix-7-x` | `fix/7-x` | `fix/7-x/` |
  | `random-thing` | `random-thing` | `random-thing/` (unrecognised → verbatim) |

- **Alias normalisation** — aliases collapse to canonical prefixes
  (`feature`→`feat`, `bugfix`→`fix`, …), the same way whether you pass the flat
  (dash) or path-like (slash) form. Configure prefixes/aliases in
  `worktree_create.yaml`.

- **Re-entrancy** — re-entering an existing branch returns its existing worktree
  instead of erroring.

- **Configurable location** (`worktree_location`):
  - `native` (default) — `<repo>/.claude/worktrees/`
  - `in-repo` — `<repo>/<in_repo_dir>/` (e.g. `.worktrees`)
  - `sibling` — `<repo-parent>/<repo><work_dir_suffix>/`

  `native`/`in-repo` are auto-added to `.git/info/exclude` so they never pollute
  `git status`.

- **Literal-branch guard** — if a branch with the literal requested name already
  exists locally (an old flat-format worktree), it is honoured as-is rather than
  normalised, so you never fork a divergent branch.

- **Fresh branches** — new branches are created from `origin/<default>` when a
  remote tracking ref exists, falling back to the local default branch.

- **Clean teardown** — when Claude Code removes one of these worktrees
  (`ExitWorktree` or session-exit cleanup), the companion `WorktreeRemove` hook
  force-removes the worktree directory and deletes its branch. The branch is
  deleted with the *safe* `git branch -d`: if it still holds unmerged commits
  the hook leaves it in place rather than destroy work.

## Configuration

`worktree_create.yaml` (bundled) provides the defaults. A project may override
by placing `.claude/hooks/worktree_create.yaml` at its repo root; project
settings merge on top of the bundled defaults.

No dependencies required — the script uses PyYAML if present and falls back to a
minimal built-in parser otherwise.

## Installation

```text
/plugin marketplace update pyeye-marketplace
/plugin install worktree-hook@pyeye-marketplace
```

> **Switching from a global hook:** plugin hooks are *additive* and deduped by
> exact command string. If you previously registered `worktree_create.py` in
> `~/.claude/settings.json`, remove that `WorktreeCreate` block when adopting
> this plugin — otherwise both run and conflict.

## Notes

These behaviours were verified empirically during testing of the installed
plugin. They are non-obvious — each one caused real confusion — so they are
captured here to save the next person the same debugging.

### This hook fires inside git repositories

Claude Code's published docs suggest `WorktreeCreate` hooks apply only to
non-git version control (SVN, Perforce, Mercurial). In practice — verified by
testing — `EnterWorktree` *does* route through a registered `WorktreeCreate`
hook inside a normal git repository, and the hook's stdout path fully overrides
the native default (`.claude/worktrees/<name>` on a `worktree-<name>` branch).
This override is the entire basis for the plugin working, so without it the
plugin would be dead code. Because this contradicts the published docs, treat it
as observed behaviour that could change across Claude Code versions rather than a
guarantee.

### Restart your session after installing/enabling

Plugin hooks load at session start, not retroactively. If you `/plugin install`
(or enable) this plugin in a session that began *before* the install,
`EnterWorktree` falls back to native behaviour (a flat `worktree-<name>`
directory and branch) because the plugin's hook isn't loaded yet. Start a fresh
session before the hook takes effect. (Hooks defined directly in `settings.json`
are auto-reloaded mid-session via the file watcher; only plugin hooks need the
restart.)

### Removing a worktree this hook created

The companion `WorktreeRemove` hook handles cleanup automatically: when Claude
Code removes one of these worktrees it fires the hook, which force-removes the
directory and safely deletes the branch (see *Clean teardown* above). You do not
need to clean up by hand in the normal case.

This is necessary because the harness delegates teardown *entirely* to the hook
for worktrees created out-of-band — verified by testing: `ExitWorktree` fires
`WorktreeRemove` but does not remove anything itself, so without this hook the
directory, its `git worktree` registration, and the branch are all left behind.
(As with the create side, this is observed behaviour that could change across
Claude Code versions.)

Two things to know:

- `ExitWorktree` still first **refuses** with "could not verify worktree state";
  confirm the removal (e.g. `discard_changes: true`) and the hook then runs.
- If the branch holds unmerged commits the hook **keeps it on purpose**. Delete
  it deliberately once you're sure: `git branch -D <type>/<name>`.

Manual fallback, if you ever need to remove one yourself:

```bash
git worktree remove --force .claude/worktrees/<type>/<name>
git branch -d <type>/<name>   # -D to force-drop an unmerged branch
```
