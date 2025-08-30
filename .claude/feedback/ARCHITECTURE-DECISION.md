# Architecture Decision: Claude Development Worktree as Learning Hub

## 🎯 Core Concept

The `claude/development` worktree serves as the **persistent learning and development hub** for Claude Code sessions.

## 🏗️ Architecture

```text
python-code-intelligence-mcp/              # Main repo (stable, on main branch)
├── .claude/                               # Base agents (reference versions)
│   └── agents/

python-code-intelligence-mcp-work/
├── claude-development/                    # PERSISTENT LEARNING HUB
│   ├── .claude/
│   │   ├── agents/                       # Evolving agent definitions
│   │   │   ├── worktree-manager.md      # Updated with learnings
│   │   │   └── ...
│   │   └── feedback/                     # Learning system
│   │       ├── logs/                     # Session feedback
│   │       ├── learnings/                # Extracted patterns
│   │       └── metrics/                  # Performance tracking
│   └── CLAUDE.md                         # Evolving instructions
│
├── feat-123-some-feature/                # Temporary worktrees for issues
├── fix-456-bug/                          # Created/destroyed as needed
└── test-789-coverage/                    # No feedback system here

```

## 🔄 Workflow

### 1. Session Startup

```bash
# Claude ALWAYS starts in claude-development worktree
cd /home/mark/GitHub/python-code-intelligence-mcp-work/claude-development
export CLAUDE_STARTUP_DIR=$(pwd)
export CLAUDE_IS_LEARNING_HUB=true
```

### 2. Learning Capture

- All agent executions log to `claude-development/.claude/feedback/`
- Learnings accumulate in this persistent location
- Agent improvements are tested here first

### 3. Issue Work

- Create temporary worktrees for specific issues
- But feedback ALWAYS goes to claude-development
- This centralizes learning regardless of which worktree you're working in

### 4. Evolution Cycle

```text
claude-development (persistent)
    ↓
Collect feedback from all sessions
    ↓
Extract patterns & learnings
    ↓
Update agents in claude-development
    ↓
Test improvements
    ↓
Eventually merge to main (periodic)
```

## 📝 Key Principles

### Why claude/development as the Hub?

1. **Persistence** - Never deleted, accumulates knowledge over time
2. **Isolation** - Experiments don't affect main branch
3. **Evolution** - Agents can improve without waiting for releases
4. **Centralization** - One place for all learning data

### How It Works

1. **Feedback Collection**

   ```bash
   # No matter which worktree you're in:
   FEEDBACK_DIR="$CLAUDE_STARTUP_DIR/.claude/feedback"
   echo "$log_entry" >> "$FEEDBACK_DIR/logs/$(date +%Y-%m-%d)-$agent.json"
   ```

2. **Agent Loading**

   ```bash
   # Agents always load from startup directory first
   AGENT_PATH="$CLAUDE_STARTUP_DIR/.claude/agents/$agent.md"
   # Fallback to main repo if not found
   ```

3. **Learning Application**
   - Improvements are made to claude-development agents
   - Tested in real sessions
   - Proven improvements eventually merge to main

## 🚀 Benefits

1. **Continuous Learning** - Every session contributes to knowledge base
2. **Rapid Evolution** - Agents improve without release cycles
3. **Safe Experimentation** - Main branch stays stable
4. **Unified Experience** - All Claude sessions benefit from collective learning

## 🔧 Implementation Requirements

### For Claude Sessions

1. **Always start in claude-development**

   ```bash
   # In user's shell config or Claude startup
   alias claude-start='cd ~/GitHub/python-code-intelligence-mcp-work/claude-development'
   ```

2. **Export learning context**

   ```bash
   export CLAUDE_LEARNING_HUB="/path/to/claude-development"
   export CLAUDE_FEEDBACK_DIR="$CLAUDE_LEARNING_HUB/.claude/feedback"
   ```

3. **Agent resolution order**
   - First: `$CLAUDE_LEARNING_HUB/.claude/agents/`
   - Second: Main repo `.claude/agents/`
   - Third: User's `~/.claude/agents/`

### For Agents

All agents should include:

```markdown
## Feedback Logging

Log all executions to: $CLAUDE_FEEDBACK_DIR/logs/
Load improvements from: $CLAUDE_FEEDBACK_DIR/learnings/
```

## 📊 Metrics & Monitoring

The claude-development worktree maintains:

- Session count tracking
- Agent performance over time
- Learning application rate
- Improvement effectiveness

## 🎯 Success Criteria

The system succeeds when:

1. Every Claude session starts in claude-development
2. All agents log feedback consistently
3. Learnings are automatically applied
4. Agent success rates improve measurably
5. Knowledge persists across sessions

## 🔄 Merge Strategy

Periodically (weekly/monthly):

1. Review accumulated learnings
2. Test stable improvements
3. Create PR from claude/development → main
4. Merge proven improvements
5. Reset for next learning cycle

## ⚠️ Important Notes

1. **Never delete claude-development worktree** - It's the knowledge repository
2. **Always start sessions there** - Even when working on other issues
3. **Feedback always goes there** - Regardless of current worktree
4. **Agents evolve there** - Before merging to main

## 🎉 Result

This architecture creates a true learning system where:

- Every session makes agents smarter
- Knowledge accumulates permanently
- Improvements deploy continuously
- The system gets better every day

---

*Decision Date: 2025-08-30*
*Architecture: Claude Development Worktree as Persistent Learning Hub*
