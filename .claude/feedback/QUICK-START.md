# Agent Self-Improvement System - Quick Start

## 🎯 The Big Picture

### claude-development worktree = Learning Hub

All Claude sessions should start here to enable continuous learning and improvement.

## 🚀 Session Startup (MANDATORY)

```bash
# Always start Claude in the learning hub
cd /home/mark/GitHub/python-code-intelligence-mcp-work/claude-development

# Export learning context
export CLAUDE_LEARNING_HUB=$(pwd)
export CLAUDE_FEEDBACK_DIR="$CLAUDE_LEARNING_HUB/.claude/feedback"
export CLAUDE_WORKING_DIR=$(pwd)

echo "Learning hub active: $CLAUDE_LEARNING_HUB"
```

## 📝 When Things Go Wrong

### 1. Log It Immediately

```bash
# Quick logging during agent execution
echo '{"timestamp":"'$(date -Iseconds)'","agent":"worktree-manager","issue":"cd failed","recovery":"used absolute path"}' >> $CLAUDE_FEEDBACK_DIR/logs/$(date +%Y-%m-%d)-worktree-manager.json
```

### 2. Check for Patterns

```bash
# See if this issue has happened before
python $CLAUDE_FEEDBACK_DIR/analyze_agent_performance.py worktree-manager --days 7
```

### 3. Update Agent if Needed

```bash
# If pattern detected, update agent
vim $CLAUDE_LEARNING_HUB/.claude/agents/worktree-manager.md
# Add fix based on learning
```

## 📊 Weekly Review

```bash
# Generate performance reports
for agent in worktree-manager smart-commit pr-workflow; do
    echo "=== $agent ==="
    python $CLAUDE_FEEDBACK_DIR/analyze_agent_performance.py $agent --days 7
done
```

## 🔄 The Learning Loop

```text
Issue Occurs → Log It → Analyze Patterns → Update Agent → Test Fix → Share Learning
     ↑                                                                      ↓
     └──────────────────── Next Session Benefits ←─────────────────────────┘
```

## 📁 What's Where

```text
claude-development/.claude/
├── agents/                    # Evolving agent definitions
│   ├── worktree-manager.md   # Updated with path fixes
│   └── smart-commit.md       # Now logs feedback
├── feedback/
│   ├── logs/                 # Raw execution logs (git-ignored)
│   ├── learnings/            # Extracted patterns (git-tracked)
│   ├── metrics/              # Performance data (git-ignored)
│   └── analyze_agent_performance.py  # Analysis tool
```

## ✅ Checklist for Agent Developers

- [ ] Start session in claude-development worktree
- [ ] Export CLAUDE_FEEDBACK_DIR
- [ ] Log agent issues when they occur
- [ ] Run analysis weekly
- [ ] Update agents based on patterns
- [ ] Document learnings
- [ ] Test improvements

## 🎉 Why This Matters

- **Every session makes agents smarter**
- **Issues get fixed once, benefit everyone**
- **Performance improves measurably**
- **Knowledge persists across sessions**

## 🚨 Remember

1. **claude-development is PERMANENT** - Never delete it
2. **All feedback goes here** - Even when working in other worktrees
3. **Agents evolve here** - Test improvements before merging to main
4. **Knowledge accumulates** - The system gets smarter every day

---

*For detailed documentation:*

- [Full System Design](README-SELF-IMPROVEMENT.md)
- [Architecture Decision](ARCHITECTURE-DECISION.md)
- [Implementation Details](IMPLEMENTATION-SUMMARY.md)
