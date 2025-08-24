# Claude Worktree-Aware Development Workflow

## Overview

This document describes how to develop Claude-specific features (agents, instructions, commands) using a worktree-aware workflow that Claude can understand and follow.

## The Core Principle

**Where you START Claude determines the context for Claude-specific files.**

- Start from main repo → Production context
- Start from worktree → Development context for that feature

## Starting Claude for Different Purposes

### For Agent Development

```bash
# 1. Create worktree for agent feature
git worktree add ../python-code-intelligence-mcp-work/feat-175-agent -b feat/175-agent main

# 2. Navigate to worktree
cd ../python-code-intelligence-mcp-work/feat-175-agent

# 3. Start Claude FROM the worktree
claude

# Now:
# - /agents shows agents from THIS directory
# - Edits to .claude/ stay in THIS directory
# - CLAUDE.md updates are in THIS directory
```

### For Regular Feature Development

```bash
# Can start from main repo
cd /home/mark/GitHub/python-code-intelligence-mcp
claude

# Or from a feature worktree
cd ../python-code-intelligence-mcp-work/feat-180-feature
claude
```

## Claude's Startup Behavior

When Claude starts, it should:

1. **Detect context**:

```bash
pwd  # Where am I?
git worktree list | grep $(pwd)  # Am I in a worktree?
```

1. **Store context**:

```bash
export CLAUDE_STARTUP_DIR=$(pwd)
export CLAUDE_IS_WORKTREE=true/false
```

1. **Adapt behavior**:

- If in worktree → Claude files edited here
- If in main → Be careful, maybe create worktree

## Workflow Patterns

### Pattern 1: Developing Claude Agent in Worktree

```markdown
Session starts in: feat-175-cross-platform-agent/

User: "Let's improve the agent to handle file permissions"
Claude: "I'll edit the agent in the current worktree's .claude/agents/"
[Edits .claude/agents/cross-platform-validator.md]

User: "Now work on issue 180 for performance"
Claude: "I'll create a sibling worktree for issue 180, but keep Claude files here"
[Creates ../feat-180-performance/]
[But agent edits stay in feat-175 worktree]
```

### Pattern 2: Working on Multiple Issues

```markdown
Session starts in: feat-175-cross-platform-agent/

User: "Also need to fix issue 181"
Claude: "Creating sibling worktree for issue 181..."
[Creates ../feat-181-bugfix/ at same level]

User: "Update the agent based on what we learned"
Claude: "Updating agent in startup worktree..."
[Edits $CLAUDE_STARTUP_DIR/.claude/agents/]
```

### Pattern 3: Testing Agents

```markdown
Session starts in: feat-175-cross-platform-agent/

User: "Test the agent"
Claude: "/agents"  # Shows agents from THIS directory
[Agent is immediately available]

User: "Run it on the main codebase"
Claude: "I'll run the agent on the main repo code..."
[Can analyze ../python-code-intelligence-mcp/ from here]
```

## Rules for Claude

### When Started from a Worktree

1. **Claude files belong to startup worktree**:
   - `.claude/agents/*` → Edit in `$CLAUDE_STARTUP_DIR`
   - `CLAUDE.md` → Edit in `$CLAUDE_STARTUP_DIR`
   - `.claude/commands/*` → Edit in `$CLAUDE_STARTUP_DIR`

2. **New worktrees are siblings, not children**:

   ```bash
   # WRONG: git worktree add ./feat-180  # Nested
   # RIGHT: git worktree add ../feat-180  # Sibling
   ```

3. **Commit Claude changes in startup worktree**:

   ```bash
   cd $CLAUDE_STARTUP_DIR
   git add .claude/ CLAUDE.md
   git commit -m "feat: improve agent"
   ```

### When Started from Main Repo

1. **Consider creating worktree for Claude changes**:

   ```bash
   # If working on agents/instructions
   git worktree add ../feat-X-claude-updates
   cd ../feat-X-claude-updates
   # Then restart Claude from there
   ```

2. **Or carefully edit in main** (knowing you need to move changes)

## Helper Functions

Claude should define these helpers at startup:

```bash
# Check Claude context
claude_context() {
    echo "Startup dir: $CLAUDE_STARTUP_DIR"
    echo "Is worktree: $CLAUDE_IS_WORKTREE"
    echo "Branch: $CLAUDE_WORKTREE_BRANCH"
}

# Edit agent in startup context
edit_agent() {
    local agent=$1
    vim "$CLAUDE_STARTUP_DIR/.claude/agents/${agent}.md"
}

# Create sibling worktree
sibling_worktree() {
    local issue=$1
    local type=$2
    local desc=$3
    local main=$(git worktree list | head -1 | awk '{print $1}')
    cd "$main"
    git worktree add "../python-code-intelligence-mcp-work/${type}-${issue}-${desc}" \
                     -b "${type}/${issue}-${desc}"
}

# Switch to startup context
go_home() {
    cd "$CLAUDE_STARTUP_DIR"
}
```

## Benefits

1. **Natural testing**: /agents works immediately
2. **Clean commits**: Claude changes isolated in feature branch
3. **No syncing**: Single source of truth
4. **Parallel work**: Multiple issues without confusion
5. **Context preservation**: Claude always knows where its files are

## Common Scenarios

### Scenario: Long-Running Agent Development

```bash
# Monday: Start agent development
cd feat-175-agent/
claude  # Start here, work all day

# Tuesday: Continue from same place
cd feat-175-agent/
claude  # Picks up where you left off

# Wednesday: Agent done, work on other stuff
cd main/
claude  # New session for other work
```

### Scenario: Quick Agent Test

```bash
# In main repo, want to test agent idea
git worktree add ../test-agent -b test/agent-idea
cd ../test-agent
claude  # Isolated space for experimentation
# Later: git worktree remove ../test-agent
```

### Scenario: Updating Multiple Claude Features

```bash
# Start in Claude-focused worktree
cd feat-175-claude-updates/
claude

# Work on agents, instructions, commands all in one place
# Commit together as cohesive Claude enhancement
```

## Summary

The key insight: **Claude's working directory at startup is its "home" for Claude-specific files.**

This creates a natural, git-native workflow where:

- Worktrees isolate features (including Claude features)
- No manual syncing needed
- Testing is immediate
- Context is preserved throughout the session
