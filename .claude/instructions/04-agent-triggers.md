<!--
Audience: Claude Code
Purpose: Define trigger phrases and patterns that require agent usage instead of manual commands
When to update: When new agents are added or trigger patterns change
-->

# Mandatory Agent Usage

## ALWAYS Use These Agents (Never Manual Commands)

**CRITICAL**: These are TRIGGER PHRASES. When you see these patterns, you MUST use the agent, not manual commands!

**When the user says any variant of:**

### "Remove worktree for issue X" / "Delete worktree" / "Clean up worktree"

→ **IMMEDIATELY use**: `Task tool with subagent_type="worktree-manager"`
→ **NEVER use**: Manual `git worktree remove` commands
→ **Why**: Ensures safety checks for uncommitted changes and proper session tracking

### "Let's commit this" / "Commit these changes" / "Create a commit"

→ **IMMEDIATELY use**: `Task tool with subagent_type="smart-commit"`
→ **NEVER use**: Manual `git status`, `git add`, `git commit` commands

### "Validate this works on Windows/Mac/Linux" / "Check cross-platform"

→ **IMMEDIATELY use**: `Task tool with subagent_type="cross-platform-validator"`
→ **NEVER use**: Manual path checking or grep for .as_posix()

### "Create worktree" / "Setup a worktree" / "Switch to issue X" / "Clean up worktrees" / "Remove worktree" / "Worktree for issue X"

→ **IMMEDIATELY use**: `Task tool with subagent_type="worktree-manager"`
→ **NEVER use**: Manual `git worktree add`, `git worktree remove`, or any direct worktree commands
→ **INCLUDES**: "create worktree for issue 115", "make a worktree", "new worktree", etc.

**❌ WRONG:**

```bash
pwd && git worktree list  # NO! Don't check manually
gh issue view 115         # NO! The agent will handle this
git worktree add ...      # NO! Never use this directly
```

**✅ RIGHT:**

```text
User: create worktree for issue 115
Claude: I'll use the worktree-manager agent to create that worktree.
[Uses Task tool with subagent_type="worktree-manager"]
```

### "PR is merged" / "Update after merge" / "Sync after external merge"

→ **IMMEDIATELY use**: `Task tool with subagent_type="worktree-manager"`
→ **NEVER use**: Manual `git checkout`, `git merge`, `git pull` sequences
→ **Note**: Handles special cases like persistent claude/development branch

### "Push and create PR" / "Create a PR" / "Monitor CI" / "Check if CI passes"

→ **Use raw commands** (the pr-workflow agent was deleted — see "Why no pr-workflow agent" below):

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

## Composite Agent Workflows

These commands trigger multiple agents in sequence:

### "Merge and cleanup" / "Merge PR and clean up" / "Finish this PR"

→ **EXECUTE IN SEQUENCE**:

1. **Merge the PR with raw commands** (capture exit codes; verify state):

   ```bash
   # For normal feature branches:
   gh pr merge <PR-NUMBER> --merge --delete-branch
   [ $? -eq 0 ] || { echo "ERROR: merge failed"; exit 1; }

   # For claude/development (persistent — DO NOT delete):
   gh pr merge <PR-NUMBER> --merge   # no --delete-branch
   # Then update main + merge main back into claude/development:
   git -C "$(git worktree list | head -1 | awk '{print $1}')" checkout main
   git -C "$(git worktree list | head -1 | awk '{print $1}')" pull origin main
   # ... see Special Cases in 06-workflow-commits.md for the full claude/development handling

   # Verify merge state (auto-close of linked issues is async — may need a brief wait)
   gh pr view <PR-NUMBER> --json state,mergedAt,headRefDeleted
   ```

2. `Task tool with subagent_type="worktree-manager"` - Remove the worktree safely after confirming no uncommitted changes

### "PR is merged. update" / "Update after merge" / "Sync with main" / "Merged externally"

→ **IMMEDIATELY use**: `Task tool with subagent_type="worktree-manager"`
→ **Purpose**: Handle post-merge updates when PR was merged externally (via GitHub UI or by another user)
→ **Special handling**: For claude/development, updates the persistent branch without removing worktree

### "Start issue X" / "Begin work on issue X"

→ **EXECUTE IN SEQUENCE**:

1. `Task tool with subagent_type="worktree-manager"` - Create worktree for the issue
2. Review issue with `gh issue view X`
3. Create initial todo list based on issue requirements

## Available Agents

- **smart-commit**: Intelligent git commit workflow with pre-commit validation
- **cross-platform-validator**: Validates cross-platform compatibility
- **worktree-manager**: Safe worktree operations with session tracking
- **general-purpose**: For complex multi-step research tasks

**Note**: Agents are defined in `.claude/agents/` and are automatically available via the Task tool.

## Why no pr-workflow agent

The `pr-workflow` agent was deleted because it was net liability:

- Most of its work was thin wrappers over `git push` + `gh pr create` + `gh pr checks --watch` (all of which are simple, transparent, well-documented commands).
- The few genuinely-useful pieces (CI error parsing, merge composite for claude/development) had silent-wrong-success bugs (exit codes not checked, race conditions in CI run lookup, factual errors in examples).
- Documentation drifted (one example used a `--issue` flag that doesn't exist in `gh pr create`), actively misleading anyone who copied it.

Use raw `git` and `gh` commands. They're transparent, debuggable, and don't accumulate hidden bugs. `gh pr checks --watch` already does the CI-monitoring loop the agent reinvented.
