<!--
Audience: Claude Code
Purpose: Define session startup procedures and working directory management
When to update: When startup workflow or worktree management changes
-->

# Session Startup and Working Directory Management

## 🎯 SESSION STARTUP: Claude Development as Learning Hub

**MANDATORY at session start - Run immediately:**

```bash
# Claude should ALWAYS start in the claude-development worktree (learning hub)
# This is where agent improvements and feedback are collected
cd /home/mark/GitHub/python-code-intelligence-mcp-work/claude-development

# Store learning hub location
export CLAUDE_STARTUP_DIR=$(pwd)
export CLAUDE_LEARNING_HUB=$(pwd)
export CLAUDE_FEEDBACK_DIR="$CLAUDE_LEARNING_HUB/.claude/feedback"
export CLAUDE_IS_WORKTREE=$(git worktree list | grep -q "$(pwd)" && echo "true" || echo "false")
export CLAUDE_WORKTREE_BRANCH=$(git branch --show-current 2>/dev/null || echo "none")

# Initialize working directory tracking
export CLAUDE_WORKING_DIR=$(pwd)  # This can change when switching to issue worktrees

# Report context
echo "Claude Learning Hub: $CLAUDE_LEARNING_HUB"
echo "Feedback Directory: $CLAUDE_FEEDBACK_DIR"
echo "Current Branch: $CLAUDE_WORKTREE_BRANCH"
echo "Ready for continuous learning and improvement!"
```

**Why claude-development?** This persistent worktree serves as:

- **Learning Hub**: All agent feedback is collected here
- **Evolution Lab**: Improvements are tested and refined here
- **Knowledge Base**: Learning accumulates across sessions
- **Agent HQ**: Agents evolve based on real-world usage

**This determines:**

- Where Claude configuration files (.claude/) are read from (CLAUDE_LEARNING_HUB)
- Where agent/instruction edits should be saved (CLAUDE_LEARNING_HUB)
- Where feedback is logged ($CLAUDE_FEEDBACK_DIR)
- Where actual work happens (CLAUDE_WORKING_DIR - updates when switching worktrees)
- How to create new worktrees (sibling vs child)

## 🔄 CRITICAL: Working Directory Management

### The Shell Reset Problem

**Issue**: After each command, the shell working directory resets to CLAUDE_STARTUP_DIR (usually claude-development).

### Solution: Update CLAUDE_WORKING_DIR When Switching Worktrees

**When switching to work on an issue:**

```bash
# After creating/switching to issue worktree
cd ../python-code-intelligence-mcp-work/fix-123-issue-name
export CLAUDE_WORKING_DIR=$(pwd)

# Now prefix subsequent commands with cd to stay in context
cd $CLAUDE_WORKING_DIR && git status
cd $CLAUDE_WORKING_DIR && uv run pytest
```

**Better: Use a worktree switch function:**

```bash
switch_worktree() {
    local WORKTREE_PATH=$1
    cd "$WORKTREE_PATH"
    export CLAUDE_WORKING_DIR=$(pwd)
    echo "Switched working context to: $CLAUDE_WORKING_DIR"
    echo "Claude home remains: $CLAUDE_STARTUP_DIR"
}

# Usage when switching to issue worktree
switch_worktree "../python-code-intelligence-mcp-work/fix-123-issue-name"
```

### Best Practices

1. **Always update CLAUDE_WORKING_DIR** when switching to issue worktrees
2. **Prefix commands with `cd $CLAUDE_WORKING_DIR &&`** to maintain context
3. **Use absolute paths** in worktree operations to avoid confusion
4. **Check current context** with `echo $CLAUDE_WORKING_DIR` if uncertain

### Special Workflow: Claude Development Branch (Learning Hub)

The `claude-development` worktree is the **persistent learning hub** with special characteristics:

#### Standard Issue Workflow (Delete After Merge)

```bash
# Normal issue branches:
1. Create PR from feat/123-feature → main
2. Merge PR
3. Delete remote branch
4. Remove worktree (worktree-manager does this)
```

#### Claude Development Workflow (Keep and Update)

```bash
# For claude/development branch:
1. Create PR from claude/development → main
2. Merge PR (keeps branch)
3. DO NOT delete remote branch
4. DO NOT remove worktree
5. Update local branch:
   cd /home/mark/GitHub/python-code-intelligence-mcp-work/claude-development
   git checkout main
   git pull origin main
   git checkout claude/development
   git merge main  # or rebase if preferred
   git push origin claude/development
```

**Important for Agents**:

- When using `pr-workflow` agent with claude/development, specify `--no-delete-branch`
- When "merge and cleanup" is requested for claude/development, only merge - skip cleanup
- The worktree at `/home/mark/GitHub/python-code-intelligence-mcp-work/claude-development` is **persistent**
- **NEVER switch this worktree to other branches** - always create new worktrees for releases, features, etc.

**As Learning Hub**:

- **Feedback Collection**: All agent logs go to `.claude/feedback/logs/`
- **Learning Accumulation**: Patterns extracted to `.claude/feedback/learnings/`
- **Agent Evolution**: Improvements tested here before merging to main
- **Knowledge Persistence**: Never deleted, knowledge grows over time
- **Session Home**: All Claude sessions should start here
