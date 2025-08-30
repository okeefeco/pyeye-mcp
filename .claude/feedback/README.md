# Agent Feedback & Self-Improvement System

## Quick Start

This system enables Claude Code agents to learn from their experiences and improve over time.

### 1. When an Agent Has Issues

Log the issue immediately:

```bash
# Manual logging (for now)
cat >> .claude/feedback/logs/$(date +%Y-%m-%d)-worktree-manager.json << 'EOF'
{
  "timestamp": "$(date -Iseconds)",
  "agent": "worktree-manager",
  "task": "Description of what failed",
  "outcome": "failure",
  "issues": [{
    "type": "path_error",
    "description": "What went wrong",
    "impact": "high"
  }]
}
EOF
```

### 2. Analyze Agent Performance

```bash
# Generate performance report
python .claude/feedback/analyze_agent_performance.py worktree-manager --days 30

# Compare this week to last week
python .claude/feedback/analyze_agent_performance.py worktree-manager --compare

# Save metrics for tracking
python .claude/feedback/analyze_agent_performance.py worktree-manager --save-metrics
```

### 3. Update Agent Instructions

Based on analysis, update the agent's instructions:

1. Review `.claude/feedback/learnings/{agent}-learnings.md`
2. Update `.claude/agents/{agent}.md` with fixes
3. Test the improvements
4. Log the update in learnings file

## Directory Structure

```text
.claude/feedback/
├── README.md                          # This file
├── README-SELF-IMPROVEMENT.md         # Detailed documentation
├── analyze_agent_performance.py       # Analysis tool
├── logs/                              # Raw feedback logs
│   └── 2025-01-30-worktree-manager.json
├── learnings/                         # Extracted learnings
│   └── worktree-manager-learnings.md
└── metrics/                           # Performance metrics
    └── worktree-manager-metrics.json
```

## Current Status

### ✅ Implemented

- Feedback logging structure
- Performance analysis tool
- Learnings documentation
- Updated worktree-manager with path fixes

### 🚧 In Progress

- Automatic feedback capture
- Real-time learning updates
- Cross-agent knowledge sharing

### 📋 TODO

- Add feedback hooks to all agents
- Create dashboard for metrics
- Implement A/B testing for changes

## Key Learnings So Far

### 1. Path Management (Critical)

**Problem**: Shell resets between commands
**Solution**: Always use absolute paths, export CLAUDE_WORKING_DIR

### 2. Error Recovery

**Problem**: Silent failures
**Solution**: Add error checking and recovery strategies

### 3. State Validation

**Problem**: Assumptions about current state
**Solution**: Verify state before operations

## How to Contribute

When you encounter an agent issue:

1. **Log it** - Add to feedback logs
2. **Fix it** - Update agent instructions
3. **Document it** - Add to learnings
4. **Test it** - Verify the fix works
5. **Share it** - Update this README if needed

## Metrics Dashboard (Sample Output)

```text
# Agent Performance Report: worktree-manager
Generated: 2025-01-30 14:45:00
Analysis Period: Last 30 days

## Executive Summary
- Total Executions: 45
- Success Rate: 75.5%
- Error Recovery Rate: 82.0%
- Average Execution Time: 2500ms
- User Intervention Rate: 15.5%

## Top Issues:
  - path_error: 8 occurrences
  - context_loss: 5 occurrences
  - permission_denied: 2 occurrences

## Recommendations
- 🔄 3 repeated issues detected. Update agent instructions.
- ⚠️ Success rate could be improved. Review path handling.
```

## Best Practices

1. **Log Everything** - Even partial successes
2. **Be Specific** - Detailed descriptions help pattern detection
3. **Track Recovery** - Note what fixed the issue
4. **Update Promptly** - Don't let issues accumulate
5. **Test Changes** - Verify fixes before deploying

## Integration with Agents

Each agent should include this in their instructions:

```markdown
## Self-Improvement

This agent logs experiences to `.claude/feedback/logs/` for continuous improvement.
When encountering issues:
1. Log the issue with context
2. Attempt recovery
3. Report outcome to user
4. Update learnings if pattern emerges
```

## Future Enhancements

- **Real-time Monitoring**: Watch for issues as they happen
- **Automatic Updates**: Self-modify instructions based on patterns
- **Cross-Agent Learning**: Share solutions between agents
- **Performance Benchmarks**: Track improvements over time
- **User Feedback Integration**: Learn from user corrections

---

*For detailed documentation, see [README-SELF-IMPROVEMENT.md](README-SELF-IMPROVEMENT.md)*
