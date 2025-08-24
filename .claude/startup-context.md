# Claude Startup Context Detection

## 🚀 Automatic Worktree-Aware Workflow

This file helps Claude understand the context it was started from and adapt its workflow accordingly.

## Startup Detection Logic

When Claude starts, it should immediately run:

```bash
# 1. Detect current directory
pwd

# 2. Check if in a worktree
git worktree list | grep $(pwd)

# 3. Store startup context
CLAUDE_STARTUP_DIR=$(pwd)
CLAUDE_IS_WORKTREE=$(git worktree list | grep -q $(pwd) && echo "true" || echo "false")
CLAUDE_WORKTREE_BRANCH=$(git branch --show-current)
```

## Context-Aware Behavior

### If Started from a Worktree

```bash
# Example: Started from /home/mark/GitHub/python-code-intelligence-mcp-work/feat-175-cross-platform-agent
```

**Claude should understand:**

1. **This is the "home" directory** for Claude-specific files (.claude/, CLAUDE.md)
2. **Agent development** happens HERE in .claude/agents/
3. **Instruction updates** happen HERE in CLAUDE.md
4. **Other feature work** needs NEW worktrees created parallel to this one

**Workflow for new issues when in worktree:**

```bash
# Working on issue 180 while in feat-175 worktree
# DON'T create nested worktree, create sibling
cd $(git worktree list | head -1 | awk '{print $1}')  # Go to main
git worktree add ../python-code-intelligence-mcp-work/feat-180-new-feature -b feat/180-new-feature
cd ../python-code-intelligence-mcp-work/feat-180-new-feature

# But Claude files stay in startup worktree!
# Agent edits go to: $CLAUDE_STARTUP_DIR/.claude/agents/
# CLAUDE.md edits go to: $CLAUDE_STARTUP_DIR/CLAUDE.md
```

### If Started from Main Repo

```bash
# Example: Started from /home/mark/GitHub/python-code-intelligence-mcp
```

**Claude should understand:**

1. **This is production** - be careful with .claude/ changes
2. **Create worktrees** for ALL feature work
3. **Claude files** can be edited here but should be moved to worktrees for commits

## Smart Issue Handling

When user mentions a new issue number:

```python
def handle_new_issue(issue_num, current_context):
    if current_context['is_worktree']:
        if is_claude_related(issue_num):
            # Claude-related work happens in startup worktree
            print(f"Editing Claude files in {current_context['startup_dir']}")
        else:
            # Other work gets new worktree
            create_sibling_worktree(issue_num)
    else:
        # In main repo - create worktree for any work
        create_worktree(issue_num)
```

## Claude File Priority

When looking for Claude configuration/agents:

1. **First**: Check `$CLAUDE_STARTUP_DIR/.claude/`
2. **Fallback**: Check current directory `.claude/`
3. **User**: Check `~/.claude/`

This ensures Claude always uses the context it was started with.

## Workflow Commands

Claude should define these at startup:

```bash
# Show startup context
claude-context() {
    echo "Started from: $CLAUDE_STARTUP_DIR"
    echo "Is worktree: $CLAUDE_IS_WORKTREE"
    echo "Branch: $CLAUDE_WORKTREE_BRANCH"
}

# Edit agent in startup context
edit-agent() {
    $EDITOR "$CLAUDE_STARTUP_DIR/.claude/agents/$1.md"
}

# Edit CLAUDE.md in startup context
edit-instructions() {
    $EDITOR "$CLAUDE_STARTUP_DIR/CLAUDE.md"
}

# Create sibling worktree (not nested)
new-worktree() {
    local ISSUE=$1
    local TYPE=$2
    local DESC=$3
    local MAIN_REPO=$(git worktree list | head -1 | awk '{print $1}')
    cd "$MAIN_REPO"
    git worktree add "../python-code-intelligence-mcp-work/$TYPE-$ISSUE-$DESC" -b "$TYPE/$ISSUE-$DESC"
}
```

## Detection Prompts for Claude

At session start, Claude should:

1. **Detect context**: "Let me check where I was started from..."
2. **Store context**: "I'm running from [worktree/main], so Claude files are in [path]"
3. **Adapt workflow**: "Since I'm in a worktree, I'll create sibling worktrees for other issues"

## Example Session Flow

```markdown
User: "Let's work on issue 180"

Claude: [Detects it's in feat-175 worktree]
"I see I'm currently in the feat-175 worktree where we're developing Claude agents.
For issue 180, I'll create a sibling worktree while keeping Claude-specific
files in this worktree. Let me set that up..."

[Creates ../feat-180-description worktree]
[But edits to .claude/ stay in feat-175 worktree]
```

## Benefits

- **No confusion** about where Claude files live
- **Clean separation** of concerns
- **Natural workflow** that follows git patterns
- **Persistent context** across the session
- **Smart defaults** based on startup location
