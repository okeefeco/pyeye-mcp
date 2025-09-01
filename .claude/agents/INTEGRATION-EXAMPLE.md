---
name: example-with-event-learning
description: Example agent showing how to integrate with event-driven learning
tools: Bash, Read, Edit
color: cyan
---

# Example Agent with Event-Driven Learning Integration

This example shows how agents can integrate with the event-driven learning system.

## Startup: Source the Learning System

```bash
# At agent startup, source the learning functions
source "${CLAUDE_FEEDBACK_DIR:-/home/mark/GitHub/python-code-intelligence-mcp-work/claude-development/.claude/feedback}/event_driven_learning.sh"

AGENT_NAME="example-with-event-learning"

# Signal execution start (increments counter, checks thresholds)
handle_agent_event "execution_start" "$AGENT_NAME"
```

## During Execution: Track Events

```bash
# Example task function with event tracking
perform_task() {
    local task_path="$1"

    # Try the operation
    if cd "$task_path" 2>/dev/null; then
        echo "✓ Successfully changed to $task_path"
    else
        # Log the issue pattern
        handle_agent_event "issue_detected" "$AGENT_NAME" "path_error" "Failed to cd to $task_path"

        # Try recovery with absolute path
        task_path="$(realpath "$task_path" 2>/dev/null || pwd)"
        if cd "$task_path"; then
            echo "✓ Recovered using absolute path"
        else
            # Track failure
            handle_agent_event "execution_complete" "$AGENT_NAME" "failure"
            return 1
        fi
    fi

    # Continue with task...
    echo "Performing task in $(pwd)"

    # Simulate some work
    if [ -w "." ]; then
        echo "✓ Have write permissions"
    else
        # Another pattern to track
        handle_agent_event "issue_detected" "$AGENT_NAME" "permission_denied" "No write permission in $(pwd)"
    fi

    return 0
}
```

## Completion: Report Outcome

```bash
# Main execution flow
main() {
    echo "Starting $AGENT_NAME"

    # Track start
    handle_agent_event "execution_start" "$AGENT_NAME"

    # Perform the actual work
    if perform_task "$@"; then
        # Success
        handle_agent_event "execution_complete" "$AGENT_NAME" "success"
        echo "✅ Task completed successfully"
    else
        # Failure
        handle_agent_event "execution_complete" "$AGENT_NAME" "failure"
        echo "❌ Task failed"
    fi

    # The event system will automatically:
    # 1. Check if execution threshold reached (triggers learning)
    # 2. Monitor failure rate (triggers immediate fixes)
    # 3. Detect repeated patterns (applies known fixes)
}
```

## Real-Time Pattern Response

```bash
# Advanced: Agent can check for patterns in real-time
check_and_adapt() {
    local operation=$1

    # Before attempting operation, check if it's been problematic
    if grep -q "$operation.*failed" "$CLAUDE_FEEDBACK_DIR/.patterns/${AGENT_NAME}.patterns" 2>/dev/null; then
        echo "⚠️ This operation has failed before - using enhanced approach"

        # Use learned approach
        case "$operation" in
            "cd")
                echo "Using absolute paths (learned from failures)"
                USE_ABSOLUTE_PATHS=true
                ;;
            "git")
                echo "Adding retry logic (learned from failures)"
                MAX_RETRIES=5
                ;;
        esac
    fi
}
```

## Session End Hook

```bash
# At session end (or context switch)
cleanup() {
    echo "Session ending for $AGENT_NAME"

    # Trigger session-end analysis
    handle_agent_event "session_end"

    # This will:
    # - Analyze all agents active this session
    # - Apply learnings if thresholds met
    # - Update agent files if patterns detected
}

# Register cleanup
trap cleanup EXIT
```

## How It Works - The Flow

1. **Execution starts** → Counter increments → Checks if threshold reached
2. **Issues occur** → Patterns logged → Checks if pattern repeated
3. **Execution ends** → Outcome tracked → Checks failure rate
4. **Thresholds triggered** → Analysis runs → Fixes applied automatically

## Benefits of Integration

1. **No Manual Tracking** - Events logged automatically
2. **Real-Time Response** - Fixes applied during execution
3. **Adaptive Thresholds** - Adjusts based on agent performance
4. **Known Fix Database** - Common issues fixed immediately
5. **Session Persistence** - Learning continues across sessions

## Example Trigger Scenarios

### Scenario 1: Execution Threshold

```text
Agent runs 10 times → Threshold reached → Analysis triggered →
Patterns found → Agent updated → Next run uses improvements
```

### Scenario 2: High Failure Rate

```text
3 failures in last 10 runs → Failure threshold hit →
Immediate analysis → Critical fixes applied → Agent recovers
```

### Scenario 3: Pattern Detection

```text
Same error 3 times → Pattern detected → Known fix exists →
Fix applied immediately → Error stops occurring
```

## Testing the Integration

```bash
# Test execution counter
for i in {1..10}; do
    ./example-with-event-learning.sh test_task
done
# Should trigger learning after 10 executions

# Test failure tracking
for i in {1..3}; do
    ./example-with-event-learning.sh /nonexistent/path
done
# Should trigger high failure rate response

# Test pattern detection
for i in {1..3}; do
    handle_agent_event "issue_detected" "example-with-event-learning" "timeout"
done
# Should detect pattern and suggest/apply timeout fix
```

## Customizing Thresholds

Create agent-specific profile:

```bash
cat > $CLAUDE_FEEDBACK_DIR/.profiles/example-with-event-learning.profile << EOF
EXECUTION_THRESHOLD=5    # Check every 5 runs (not 10)
FAILURE_THRESHOLD=2      # React after 2 failures (not 3)
PATTERN_THRESHOLD=2      # Detect pattern after 2 occurrences
AUTO_FIX_ENABLED=true    # Apply fixes automatically
EOF
```

## Monitoring & Metrics

Check agent's learning status:

```bash
# View current counters
cat $CLAUDE_FEEDBACK_DIR/.counters/example-with-event-learning.count

# View recent outcomes
cat $CLAUDE_FEEDBACK_DIR/.outcomes/example-with-event-learning.recent

# View detected patterns
cat $CLAUDE_FEEDBACK_DIR/.patterns/example-with-event-learning.patterns

# Run manual analysis
$CLAUDE_FEEDBACK_DIR/event_driven_learning.sh check_agent example-with-event-learning
```

## The Result

Agents that integrate with event-driven learning:

- **Get smarter automatically** based on usage
- **Fix themselves** when patterns detected
- **Adapt thresholds** based on performance
- **Share knowledge** through the learning system

No cron jobs. No waiting. Just intelligent, event-driven improvement!
