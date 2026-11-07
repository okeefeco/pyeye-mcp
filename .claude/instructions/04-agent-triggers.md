<!--
Audience: Claude Code
Purpose: Map common requests to the right agent or command
When to update: When agents are added/removed or trigger patterns change
-->

# Agent & Command Triggers

Map common requests to the right tool. Some operations use a subagent; most are plain commands. Worktrees are **not** an agent operation — use native tooling (below).

## Agents to use

### "Let's commit this" / "Commit these changes" / "Create a commit"

→ **Use**: `Task tool with subagent_type="smart-commit"`
→ **NOT**: manual `git status` / `git add` / `git commit`

## Cross-platform path checks (static script — no agent)

### "Validate this works on Windows/Mac/Linux" / "Check cross-platform"

→ Run the static checker, then apply the path-utils patterns:

```bash
python scripts/check_cross_platform_paths.py src/pyeye/**/*.py
```

→ Fix per the rules in `10-cross-platform.md` (use `.as_posix()` for display/storage; `path_to_key()` / `paths_equal()` for keys/comparison).
→ The `cross-platform-validator` agent was retired (#483) — it was built on removed v2.0 tools and re-implemented, semantically, a textual pattern check the static script already does. See "Why no cross-platform-validator agent" below.

## Worktrees (native tooling + the using-git-worktrees skill — no agent)

### "Create worktree" / "Setup a worktree" / "Switch to issue X"

→ Use the native `EnterWorktree` tool (or the `Agent` tool with `isolation: "worktree"`); the superpowers `using-git-worktrees` skill is the entry point and drives this. Native tooling places the worktree under `.claude/worktrees` (gitignored) and lets the harness track and clean it up.
→ Set up the env with `uv sync --frozen` (this is a `uv` project — NOT `uv pip install` / `uv venv`; `dev` is uv's default group so it installs all dev tooling; `--frozen` installs exactly from `uv.lock` without re-resolving. Do NOT add `--all-extras` — there are no extras).
→ Switching to an existing worktree is just `cd` into it (`git worktree list` to find paths).

### "Remove worktree" / "Delete worktree" / "Clean up worktree"

→ Safety-check first, then remove with raw commands:

```bash
git -C <worktree-path> status --short      # or: python scripts/worktree_safety.py check <worktree-path>
git worktree remove <worktree-path>
```

→ NEVER `--force` without explicit user permission, and never remove a worktree with uncommitted changes (the safety rules in `01-core-rules.md` apply).

## Push / PR / CI (raw commands)

### "Push and create PR" / "Create a PR" / "Monitor CI" / "Check if CI passes"

→ **Use raw commands** (the pr-workflow agent was removed — see "Why no pr-workflow agent" below):

```bash
# Verify untracked files first (per the post-commit-verification rule)
git status --short

# Push (with -u for new branches)
git push -u origin "$(git branch --show-current)"

# Verify push succeeded
[ $? -eq 0 ] && [ "$(git rev-parse HEAD)" = "$(git rev-parse @{u})" ] || echo "ERROR: push did not sync"

# Create PR (issue-link goes in body via "Fixes #N" / "Closes #N" / "Resolves #N")
gh pr create --base <base-branch> --title "type(scope): summary (#N)" --body "$(cat <<'EOF'
## Summary
- ...

## Test plan
- [ ] ...

Fixes #<issue>
EOF
)"

# Monitor CI (built-in, blocks until terminal state)
gh pr checks --watch
```

## Composite workflows

### "Merge and cleanup" / "Merge PR and clean up" / "Finish this PR"

1. **Merge with raw commands** (capture exit codes; verify state):

   ```bash
   gh pr merge <PR-NUMBER> --squash   # squash is the only enabled method (#607); the remote branch auto-deletes
   [ $? -eq 0 ] || { echo "ERROR: merge failed"; exit 1; }

   # Auto-close of linked issues is async — verify:
   gh pr view <PR-NUMBER> --json state,mergedAt,mergeCommit
   ```

2. **Clean up** after confirming the merge landed and there are no uncommitted changes (`git -C <worktree> status --short`): `git worktree remove <worktree-path>`, then handle the local branch per "Deleting a squash-merged branch" below. NEVER `--force` without explicit permission.

### "PR is merged" / "Update after merge" / "Sync with main" / "Merged externally"

→ **Verify the merge BEFORE any cleanup** (never delete unmerged work). PRs are squash-merged, so the branch's commits are NOT on `main`. NEVER use `git branch -r --contains` / `--is-ancestor` as the check; it always says "not merged".

```bash
# 1. Confirm GitHub merged it, and that the head it merged is exactly the local tip
gh pr view <PR-NUMBER> --json state,headRefOid,mergeCommit -q '"\(.state) \(.headRefOid) \(.mergeCommit.oid)"'
git rev-parse <feature-branch>          # should equal headRefOid

# 2. Update main (a bridge-cse_* session instead fast-forwards its own worktree branch)
git checkout main && git pull origin main
```

#### Deleting a squash-merged branch

`git branch -d` ALWAYS refuses after a squash merge, so the local branch needs `git branch -D`, which is a force operation. It still needs explicit user permission (`01-core-rules.md`). Ask with the evidence: `state` = `MERGED`, and `headRefOid` equals the local tip, so every local commit was in the merged PR. If the tip differs, say so: the branch holds commits that were never merged.

The remote branch is deleted automatically on merge (`delete_branch_on_merge`). Worktrees removed through the worktree-hook plugin detect squash merges themselves and delete the branch (see `plugins/worktree-hook/README.md`).

### "Start issue X" / "Begin work on issue X"

1. Create an isolated worktree (native `EnterWorktree` / the `using-git-worktrees` skill — see Worktrees above)
2. Review the issue: `gh issue view X`
3. Create an initial todo list from the issue requirements

## Available agents

- **smart-commit**: git commit workflow with pre-commit validation
- **general-purpose**: complex multi-step research

Agents live in `.claude/agents/` and are available via the Task tool.

## Why no pr-workflow agent

There is no `pr-workflow` agent, by design:

- Most of that work is thin wrappers over `git push` + `gh pr create` + `gh pr checks --watch` — simple, transparent, well-documented commands.
- The few genuinely-useful pieces (CI error parsing, merge composites) are prone to silent-wrong-success bugs (exit codes not checked, race conditions in CI run lookup) and documentation drift.

Use raw `git` and `gh` commands. They're transparent, debuggable, and don't accumulate hidden bugs. `gh pr checks --watch` already does the CI-monitoring loop.

## Why no cross-platform-validator agent

The `cross-platform-validator` agent was retired (#483):

- It was built on the Jedi-shaped tools removed in v2.0 (`find_symbol`, `get_type_info`, `find_imports`, `get_module_info`, `list_modules`) plus `find_references` / `get_call_hierarchy` (themselves removed in #505), so it could not run as written.
- A 1:1 rename to the new primitives doesn't restore it: its discovery relied on fuzzy symbol search, find-references, and find-imports of arbitrary modules — capabilities the redesign intentionally dropped.
- Its core job (finding code matching a *pattern* like `str(path)`) is a textual search, which pyeye is explicitly not for. `scripts/check_cross_platform_paths.py` already does that statically; the rules live in `10-cross-platform.md`.
