---
name: example-agent-with-learning
description: Template showing how agents can check for and apply learnings at runtime
tools: Bash, Read, Edit, MultiEdit
color: purple
---

# Example Agent with Self-Learning Integration

## 🧠 Learning Check at Startup

Before executing main task, check for recent learnings:

```bash
# Set learning context
AGENT_NAME="example-agent"
LEARNING_DIR="${CLAUDE_FEEDBACK_DIR:-$CLAUDE_LEARNING_HUB/.claude/feedback}"

# Check for recent learnings (updated in last 7 days)
RECENT_LEARNINGS=$(find "$LEARNING_DIR/learnings" -name "${AGENT_NAME}-*.md" -mtime -7 2>/dev/null)

if [ -n "$RECENT_LEARNINGS" ]; then
    echo "📚 Found recent learnings - applying patterns..."
    # Read and apply key patterns

    # Example: Check for path-related learnings
    if grep -q "absolute.*path" "$RECENT_LEARNINGS" 2>/dev/null; then
        echo "✓ Applying learning: Using absolute paths"
        USE_ABSOLUTE_PATHS=true
    fi

    # Example: Check for error recovery patterns
    if grep -q "retry.*pattern" "$RECENT_LEARNINGS" 2>/dev/null; then
        echo "✓ Applying learning: Enhanced retry logic"
        MAX_RETRIES=5  # Increased from default 3
    fi
fi

# Version tracking
AGENT_VERSION="1.0.0"
LAST_UPDATED="2025-01-30"
echo "Agent version: $AGENT_VERSION (updated: $LAST_UPDATED)"
```

## 📝 Main Task Execution with Learning Integration

```bash
# Example task with learnings applied
perform_task() {
    local task_path="$1"

    # Apply learning: Use absolute paths if learned
    if [ "$USE_ABSOLUTE_PATHS" = true ]; then
        task_path="$(realpath "$task_path" 2>/dev/null || echo "$task_path")"
        echo "Using absolute path: $task_path"
    fi

    # Apply learning: Enhanced retry logic
    local retry_count=0
    local max_retries="${MAX_RETRIES:-3}"

    while [ "$retry_count" -lt "$max_retries" ]; do
        if execute_operation "$task_path"; then
            log_success
            break
        else
            retry_count=$((retry_count + 1))
            log_retry "$retry_count" "$max_retries"

            # Apply recovery strategies from learnings
            if [ -f "$LEARNING_DIR/learnings/${AGENT_NAME}-recovery-strategies.md" ]; then
                apply_recovery_strategy "$retry_count"
            fi
        fi
    done

    # Log if excessive retries needed (feeds back into learning)
    if [ "$retry_count" -ge 3 ]; then
        log_learning_opportunity "high_retry_count" "$retry_count"
    fi
}
```

## 🔄 Continuous Feedback Logging

```bash
# Log successful patterns for reinforcement
log_success() {
    echo '{
        "timestamp": "'$(date -Iseconds)'",
        "agent": "'$AGENT_NAME'",
        "event": "success",
        "applied_learnings": ["absolute_paths", "enhanced_retry"],
        "performance": "improved"
    }' >> "$LEARNING_DIR/logs/$(date +%Y-%m-%d)-$AGENT_NAME.json"
}

# Log issues for pattern detection
log_issue() {
    local issue_type="$1"
    local description="$2"

    echo '{
        "timestamp": "'$(date -Iseconds)'",
        "agent": "'$AGENT_NAME'",
        "event": "issue",
        "type": "'$issue_type'",
        "description": "'$description'",
        "context": {
            "pwd": "'$(pwd)'",
            "agent_version": "'$AGENT_VERSION'"
        }
    }' >> "$LEARNING_DIR/logs/$(date +%Y-%m-%d)-$AGENT_NAME.json"
}

# Log potential learning opportunities
log_learning_opportunity() {
    local pattern="$1"
    local details="$2"

    echo '{
        "timestamp": "'$(date -Iseconds)'",
        "agent": "'$AGENT_NAME'",
        "event": "learning_opportunity",
        "pattern": "'$pattern'",
        "details": "'$details'",
        "suggestion": "Review for potential agent update"
    }' >> "$LEARNING_DIR/logs/$(date +%Y-%m-%d)-$AGENT_NAME.json"
}
```

## 🎯 Self-Improvement Triggers

The agent identifies when it needs updates:

```bash
# Check if struggling with repeated issues
check_for_repeated_issues() {
    local today_issues=$(grep -c '"event":"issue"' "$LEARNING_DIR/logs/$(date +%Y-%m-%d)-$AGENT_NAME.json" 2>/dev/null || echo 0)

    if [ "$today_issues" -gt 3 ]; then
        echo "⚠️ Multiple issues today ($today_issues) - agent may need update"
        echo "Run: python $LEARNING_DIR/analyze_agent_performance.py $AGENT_NAME --days 1"

        # Suggest specific improvements
        suggest_improvements
    fi
}

# Suggest improvements based on patterns
suggest_improvements() {
    echo "📋 Suggested improvements based on today's issues:"

    # Check for common patterns
    if grep -q "path.*not.*found" "$LEARNING_DIR/logs/$(date +%Y-%m-%d)-$AGENT_NAME.json" 2>/dev/null; then
        echo "  - Add path validation before operations"
    fi

    if grep -q "permission.*denied" "$LEARNING_DIR/logs/$(date +%Y-%m-%d)-$AGENT_NAME.json" 2>/dev/null; then
        echo "  - Add permission checks and recovery"
    fi

    if grep -q "timeout" "$LEARNING_DIR/logs/$(date +%Y-%m-%d)-$AGENT_NAME.json" 2>/dev/null; then
        echo "  - Implement timeout handling and retries"
    fi
}
```

## 📊 Performance Self-Assessment

```bash
# At end of execution, assess performance
assess_performance() {
    local start_time="$1"
    local end_time="$2"
    local execution_time=$((end_time - start_time))

    # Compare to historical average
    local avg_time=$(get_average_execution_time)

    if [ "$execution_time" -gt $((avg_time * 2)) ]; then
        log_learning_opportunity "slow_execution" "Time: ${execution_time}s (avg: ${avg_time}s)"
        echo "⚠️ Execution slower than usual - check for optimization opportunities"
    elif [ "$execution_time" -lt $((avg_time / 2)) ]; then
        log_success
        echo "✅ Execution faster than average - learnings are working!"
    fi
}

# Get historical average from metrics
get_average_execution_time() {
    if [ -f "$LEARNING_DIR/metrics/$AGENT_NAME-metrics.json" ]; then
        # Extract average from metrics (simplified)
        grep "avg_execution_time" "$LEARNING_DIR/metrics/$AGENT_NAME-metrics.json" | grep -o '[0-9]*' | head -1
    else
        echo "30"  # Default 30 seconds
    fi
}
```

## 🔄 Auto-Update Check

```bash
# Check if agent file has been updated since last run
check_for_updates() {
    local agent_file="$CLAUDE_LEARNING_HUB/.claude/agents/$AGENT_NAME.md"
    local last_run_file="$LEARNING_DIR/.last_run_$AGENT_NAME"

    if [ -f "$last_run_file" ] && [ -f "$agent_file" ]; then
        if [ "$agent_file" -nt "$last_run_file" ]; then
            echo "🔄 Agent has been updated since last run!"
            echo "New capabilities may be available"

            # Could parse changelog from agent file
            grep -A3 "## Recent Updates" "$agent_file" 2>/dev/null || true
        fi
    fi

    # Update last run timestamp
    touch "$last_run_file"
}
```

## 📚 Knowledge Sharing

```bash
# Check if other agents have solved similar problems
check_cross_agent_learnings() {
    local issue_type="$1"

    echo "🔍 Checking if other agents have solved similar issues..."

    # Search all agent learnings for solutions
    for learning_file in "$LEARNING_DIR/learnings"/*-learnings.md; do
        if [ -f "$learning_file" ] && grep -q "$issue_type" "$learning_file" 2>/dev/null; then
            local other_agent=$(basename "$learning_file" | cut -d- -f1)
            echo "💡 Found solution in $other_agent agent's learnings"

            # Extract and apply solution
            grep -A5 "$issue_type" "$learning_file" | head -6
        fi
    done
}
```

## 🎯 Complete Execution Flow with Learning

```bash
# Main execution with full learning integration
main() {
    echo "Starting $AGENT_NAME v$AGENT_VERSION"

    # 1. Check for updates and learnings
    check_for_updates
    check_for_recent_learnings

    # 2. Execute task with learned optimizations
    local start_time=$(date +%s)
    perform_task "$@"
    local end_time=$(date +%s)

    # 3. Assess performance
    assess_performance "$start_time" "$end_time"

    # 4. Check for repeated issues
    check_for_repeated_issues

    # 5. Log completion
    echo "✅ Task completed with continuous learning active"
}

# Run main function
main "$@"
```

## 🔮 Future Learning Capabilities

This template is ready for:

1. **Dynamic pattern loading** - Read patterns from learnings at runtime
2. **A/B testing** - Try different strategies and measure success
3. **Predictive warnings** - Alert before likely failures
4. **Auto-optimization** - Tune parameters based on performance
5. **Cross-agent knowledge transfer** - Share solutions between agents

## 📝 Notes for Agent Developers

When creating new agents:

1. **Copy this template** as starting point
2. **Add agent-specific learnings** in the execution logic
3. **Log all significant events** for pattern detection
4. **Check for updates** at startup
5. **Share learnings** through the feedback system

Remember: The more data logged, the smarter agents become!
