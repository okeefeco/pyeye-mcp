# Agent Self-Improvement & Learning System

## Overview

This document describes the self-improvement feedback mechanism for Claude Code agents, enabling them to learn from issues, adapt their behavior, and improve over time.

## 🎯 Core Principles

1. **Capture Issues**: Document problems as they occur
2. **Analyze Patterns**: Identify recurring issues
3. **Update Instructions**: Evolve agent behavior based on learnings
4. **Track Improvements**: Measure success of changes
5. **Share Knowledge**: Cross-agent learning

## 📁 Feedback Structure

### Directory Layout

```text
.claude/
├── agents/
│   ├── worktree-manager.md
│   ├── smart-commit.md
│   └── ...
├── feedback/
│   ├── logs/
│   │   ├── 2025-01-30-worktree-manager.json
│   │   ├── 2025-01-30-smart-commit.json
│   │   └── ...
│   ├── learnings/
│   │   ├── worktree-manager-learnings.md
│   │   ├── smart-commit-learnings.md
│   │   └── ...
│   └── metrics/
│       └── agent-performance.json
```

## 📝 Feedback Log Format

Each agent execution should log feedback in JSON format:

```json
{
  "timestamp": "2025-01-30T14:43:40.896644",
  "agent": "worktree-manager",
  "session_id": "claude-session-xyz",
  "task": "Create worktree for issue 115",
  "outcome": "partial_success",
  "issues": [
    {
      "type": "path_error",
      "description": "Failed to cd to relative path from wrong directory",
      "context": "Shell reset to startup directory after git worktree add",
      "impact": "high"
    }
  ],
  "successes": [
    {
      "type": "worktree_created",
      "description": "Successfully created worktree with correct branch naming"
    }
  ],
  "suggestions": [
    "Always use absolute paths for directory changes",
    "Store and restore CLAUDE_WORKING_DIR after shell resets"
  ],
  "execution_time_ms": 3500,
  "tools_used": ["Bash", "TodoWrite"],
  "error_recovery": true
}
```

## 🔄 Learning Loop Process

### 1. Immediate Feedback (During Execution)

When an agent encounters an issue:

```bash
# Agent should log the issue immediately
echo '{
  "timestamp": "'$(date -Iseconds)'",
  "agent": "worktree-manager",
  "issue": "cd failed due to shell reset",
  "recovery": "using absolute path instead"
}' >> ~/.claude/feedback/logs/$(date +%Y-%m-%d)-worktree-manager.json
```

### 2. Post-Execution Analysis

After each agent run, analyze what happened:

```python
# Pseudocode for analysis
def analyze_agent_execution(agent_name, session_id):
    # Collect all logs from session
    logs = load_logs(agent_name, session_id)

    # Identify patterns
    patterns = {
        "repeated_errors": find_repeated_errors(logs),
        "recovery_strategies": extract_successful_recoveries(logs),
        "performance_issues": identify_slow_operations(logs)
    }

    # Generate learnings
    learnings = generate_learnings(patterns)

    # Update agent instructions if needed
    if should_update_agent(learnings):
        update_agent_instructions(agent_name, learnings)
```

### 3. Learning Extraction

Convert feedback into actionable learnings:

```markdown
## Learnings for worktree-manager

### Issue: Shell Directory Reset (Encountered 5 times)

**Problem**: After `git worktree add`, the shell resets to CLAUDE_STARTUP_DIR

**Root Cause**: Each Bash command runs in isolation, directory context not preserved

**Solution**:
1. Always use absolute paths
2. Export and restore CLAUDE_WORKING_DIR
3. Chain commands with && when context matters

**Updated Instruction**:
```bash
# OLD (problematic)
git worktree add ../work/feat-123 -b feat/123
cd ../work/feat-123

# NEW (reliable)
WORK_DIR="/absolute/path/to/work/feat-123"
git worktree add "$WORK_DIR" -b feat/123
cd "$WORK_DIR" && export CLAUDE_WORKING_DIR=$(pwd)
```

### Issue: Permission Errors on Windows (Encountered 3 times)

**Problem**: chmod operations fail silently on Windows

**Solution**: Add platform detection and conditional chmod

**Updated Instruction**: Check OS before chmod operations

```text
```

## 🚀 Implementation Strategy

### Phase 1: Manual Feedback Collection

1. Create feedback directory structure
2. Manually log issues during agent execution
3. Weekly review of feedback logs
4. Manual updates to agent instructions

### Phase 2: Semi-Automated Collection

1. Add feedback hooks to agent templates
2. Automatic JSON logging of issues
3. Simple analysis scripts to find patterns
4. Suggested updates for human review

### Phase 3: Full Learning Loop

1. Real-time feedback collection
2. Automatic pattern detection
3. A/B testing of instruction changes
4. Continuous improvement metrics

## 📊 Success Metrics

Track these metrics to measure improvement:

```json
{
  "agent": "worktree-manager",
  "period": "2025-01",
  "metrics": {
    "success_rate": 0.85,
    "error_recovery_rate": 0.92,
    "avg_execution_time_ms": 2500,
    "unique_errors": 3,
    "repeated_errors": 1,
    "instruction_updates": 2,
    "user_interventions_required": 0.15
  },
  "improvements": {
    "success_rate_change": "+0.10",
    "execution_time_change": "-500ms",
    "error_reduction": "-40%"
  }
}
```

## 🔧 Quick Fixes Based on Current Issues

### For worktree-manager

1. **Always use absolute paths**

   ```bash
   MAIN_REPO="/home/mark/GitHub/pyeye-mcp"
   WORK_DIR="$MAIN_REPO-work/feat-123"
   ```

2. **Preserve context across commands**

   ```bash
   export CLAUDE_WORKING_DIR=$(pwd)
   # After any directory change:
   cd "$SOME_DIR" && export CLAUDE_WORKING_DIR=$(pwd)
   ```

3. **Check before assuming**

   ```bash
   # Don't assume worktree creation succeeded
   if git worktree add "$WORK_DIR" -b "$BRANCH"; then
       cd "$WORK_DIR"
   else
       echo "Failed to create worktree"
       exit 1
   fi
   ```

### For all agents

1. **Error handling first**
   - Check command success before proceeding
   - Log failures with context
   - Provide recovery strategies

2. **Platform awareness**
   - Test for OS-specific behaviors
   - Use cross-platform alternatives
   - Document platform limitations

3. **State validation**
   - Verify assumptions before operations
   - Check current directory, branch, etc.
   - Report state clearly to user

## 📚 Knowledge Sharing

### Cross-Agent Learnings

Some learnings apply to multiple agents:

```markdown
## Universal Agent Learnings

### Shell Context Management
- Applies to: ALL agents using Bash
- Learning: Shell resets between commands
- Solution: Export critical variables, use absolute paths

### Git Operations
- Applies to: worktree-manager, smart-commit
- Learning: Git commands can fail silently
- Solution: Always check exit codes, parse output

### File System Operations
- Applies to: ALL agents
- Learning: Relative paths are unreliable
- Solution: Resolve to absolute paths early
```

## 🎯 Next Steps

1. **Immediate**: Update worktree-manager with absolute path usage
2. **This Week**: Create feedback logging function for all agents
3. **This Month**: Build analysis tool to find patterns
4. **This Quarter**: Implement automatic instruction updates

## 📝 Template for Agent Updates

When updating an agent based on learnings:

```markdown
## Update: [Agent Name] - [Date]

### Issue Addressed
[Description of the problem]

### Root Cause
[Why it happened]

### Solution Implemented
[What was changed]

### Test Case
[How to verify the fix works]

### Rollback Plan
[How to revert if issues arise]
```

## 🔍 Monitoring & Alerts

Set up monitoring for critical agent failures:

1. **Failure threshold**: Alert if success rate < 70%
2. **Repeated errors**: Alert if same error occurs 3+ times
3. **Performance degradation**: Alert if execution time increases 50%
4. **User intervention**: Alert if manual fixes required > 25%

## 🤝 Contributing to Agent Improvement

When you encounter an agent issue:

1. **Document it** in the feedback log
2. **Attempt recovery** and note what worked
3. **Suggest improvement** in the feedback
4. **Update instructions** if you have a fix
5. **Share learning** in the learnings file

Remember: Every issue is an opportunity for the system to improve!
