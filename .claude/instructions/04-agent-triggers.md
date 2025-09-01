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

→ **IMMEDIATELY use**: `Task tool with subagent_type="pr-workflow"`
→ **NEVER use**: Manual `git push`, `gh pr create`, `gh run list` sequences

## Composite Agent Workflows

These commands trigger multiple agents in sequence:

### "Merge and cleanup" / "Merge PR and clean up" / "Finish this PR"

→ **EXECUTE IN SEQUENCE**:

1. `Task tool with subagent_type="pr-workflow"` - Merge the PR, update main, delete remote branch
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
- **pr-workflow**: Complete PR lifecycle - push, create/update PR, monitor CI
- **general-purpose**: For complex multi-step research tasks

**Note**: Agents are defined in `.claude/agents/` and are automatically available via the Task tool.
