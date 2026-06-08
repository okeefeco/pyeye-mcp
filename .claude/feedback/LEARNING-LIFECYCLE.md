# Agent Learning Lifecycle: From Issue to Intelligence

## 🔄 The Complete Learning Loop

### Phase 1: Issue Detection & Logging (Real-time)

**When**: During agent execution
**Who**: The agent itself or Claude observing failure

```bash
# Agent encounters issue and logs it immediately
echo '{
    "timestamp": "'$(date -Iseconds)'",
    "agent": "worktree-manager",
    "issue": "cd to relative path failed",
    "context": "shell reset after git worktree add",
    "attempted_recovery": "switched to absolute path",
    "outcome": "success_after_recovery"
}' >> $CLAUDE_FEEDBACK_DIR/logs/$(date +%Y-%m-%d)-worktree-manager.json
```

### Phase 2: Pattern Recognition (Daily/Weekly)

**When**: End of session or weekly review
**Who**: Claude or human developer

```bash
# Analyze patterns
python $CLAUDE_FEEDBACK_DIR/analyze_agent_performance.py worktree-manager --days 7

# If pattern detected (e.g., same issue 3+ times), extract learning
```

### Phase 3: Learning Documentation (Weekly)

**When**: After pattern confirmed
**Who**: Claude or human developer

```markdown
# In .claude/feedback/learnings/worktree-manager-learnings.md

## Pattern: Shell Directory Reset
Frequency: 5 occurrences this week
Solution: Always use absolute paths after git operations
```

### Phase 4: Agent Update (Immediate after learning)

**When**: As soon as learning is documented
**Who**: Claude or human developer

```bash
# Update agent with fix
vim $CLAUDE_LEARNING_HUB/.claude/agents/worktree-manager.md
# Add: "ALWAYS use absolute paths: WORK_DIR='/absolute/path'"
```

### Phase 5: Agent Becomes Smarter (Next invocation)

**When**: Next time agent is called via Task tool
**Who**: Automatic - agent reads updated instructions

## 🎯 When Agents Actually Get Smarter

### The Key Moment: Agent Invocation

When you use the Task tool:

```python
Task(subagent_type="worktree-manager", prompt="Create worktree for issue 150")
```

**What happens:**

1. Task tool loads `$CLAUDE_LEARNING_HUB/.claude/agents/worktree-manager.md`
2. Agent gets the LATEST version with all accumulated improvements
3. Agent now knows to use absolute paths (from previous learning)
4. Issue doesn't repeat!

## 📅 Recommended Update Cycles

### Immediate Updates (Critical Issues)

**Trigger**: Agent completely fails or requires user intervention
**Action**: Update agent immediately after first occurrence

```bash
# Critical failure detected
if [ "$AGENT_FAILED_COMPLETELY" = true ]; then
    # Update agent RIGHT NOW
    echo "⚠️ Critical issue - updating agent immediately"
    # Add fix to agent instructions
    # Test fix
    # Agent is smarter for next run
fi
```

### Daily Updates (Common Issues)

**Trigger**: Issue occurred 2+ times in one day
**Action**: End-of-day agent update

```bash
# Daily review (could be automated)
for agent in worktree-manager smart-commit; do
    issues_today=$(grep -c "issue" $CLAUDE_FEEDBACK_DIR/logs/$(date +%Y-%m-%d)-$agent.json 2>/dev/null || echo 0)
    if [ "$issues_today" -gt 2 ]; then
        echo "📝 $agent needs update - $issues_today issues today"
    fi
done
```

### Weekly Updates (Pattern-based)

**Trigger**: Weekly performance review
**Action**: Batch updates based on patterns

```bash
# Weekly learning extraction
python $CLAUDE_FEEDBACK_DIR/analyze_agent_performance.py worktree-manager --days 7
# Review patterns
# Update agents with proven solutions
# Test improvements
```

## 🤖 Automatic vs Manual Learning

### Currently: Semi-Automatic

1. **Automatic**: Logging issues
2. **Manual**: Analyzing patterns
3. **Manual**: Updating agents
4. **Automatic**: Agents reading updates

### Future: Fully Automatic

```python
# Pseudo-code for automatic learning
def auto_learn():
    # Every hour
    patterns = analyze_recent_logs()

    if patterns.repeated_issue_count > 3:
        # Generate fix
        fix = generate_solution(patterns)

        # Update agent
        agent_content = read_agent(patterns.agent_name)
        updated_content = inject_learning(agent_content, fix)
        write_agent(patterns.agent_name, updated_content)

        # Log the automatic update
        log_learning_applied(patterns.agent_name, fix)
```

## 🔍 How to Verify Agents Are Getting Smarter

### 1. Check Agent Version

```bash
# Add version tracking to agents
grep "Learning Version:" $CLAUDE_LEARNING_HUB/.claude/agents/worktree-manager.md
# Learning Version: 1.3 (Updated 2025-01-30 with path fixes)
```

### 2. Track Success Rates

```bash
# Compare this week to last week
python $CLAUDE_FEEDBACK_DIR/analyze_agent_performance.py worktree-manager --compare
# Success rate: 85% (was 65%) 📈 +20%
```

### 3. Monitor Issue Recurrence

```bash
# Check if known issues still occur
grep "cd.*failed" $CLAUDE_FEEDBACK_DIR/logs/$(date +%Y-%m-%d)-*.json
# Should see fewer occurrences after fix applied
```

## 🚀 Immediate Implementation Plan

### Step 1: Add Learning Checks to Agents

```markdown
## Self-Check Before Execution

1. Check for recent learnings:
   - Look for updates in $CLAUDE_FEEDBACK_DIR/learnings/{agent}-learnings.md
   - Apply any new patterns found

2. Version check:
   - Current version: 1.3
   - Last updated: 2025-01-30
```

### Step 2: Create Update Triggers

```bash
# In agent execution
if [ "$RETRY_COUNT" -gt 3 ]; then
    echo "⚠️ High retry count - agent may need update"
    echo "Check: $CLAUDE_FEEDBACK_DIR/learnings/ for patterns"
fi
```

### Step 3: Implement Learning Hooks

```bash
# At agent startup
AGENT_NAME="worktree-manager"
LAST_LEARNING=$(ls -t $CLAUDE_FEEDBACK_DIR/learnings/$AGENT_NAME-*.md 2>/dev/null | head -1)
if [ -n "$LAST_LEARNING" ]; then
    echo "📚 Loading recent learnings from: $LAST_LEARNING"
    # Could dynamically load patterns
fi
```

## 📊 Success Metrics

The learning system is working when:

1. **Issue recurrence drops** - Same problems happen less frequently
2. **Success rate increases** - Agents succeed more often
3. **User interventions decrease** - Less manual fixing needed
4. **Time to resolution improves** - Issues fixed faster
5. **Knowledge spreads** - Learnings from one agent help others

## 🎯 The Magic Moment

**The agent becomes smarter the INSTANT you update its .md file!**

Next time the Task tool loads that agent, it gets all the improvements. No restart needed, no cache to clear - just immediate intelligence upgrade!

## 🔮 Future: Real-time Learning

Imagine agents that:

1. **Learn during execution** - Update themselves mid-task
2. **Share knowledge instantly** - Broadcast solutions to other agents
3. **Predict issues** - Warn before problems occur
4. **Suggest improvements** - "I noticed a pattern, should I update myself?"

But even now, with semi-automatic learning, agents get smarter with every update cycle!

---

*Remember: The sooner you update the agent file, the sooner it gets smarter. Don't wait for perfection - incremental improvements compound quickly!*
