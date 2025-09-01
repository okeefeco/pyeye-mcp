#!/bin/bash

# Event-Driven Learning System
# Triggers learning updates based on events, not time

set -e

# Configuration
FEEDBACK_DIR="${CLAUDE_FEEDBACK_DIR:-$(dirname "$0")}"
LEARNING_HUB="${CLAUDE_LEARNING_HUB:-$(dirname $(dirname "$FEEDBACK_DIR"))}"
COUNTERS_DIR="$FEEDBACK_DIR/.counters"
OUTCOMES_DIR="$FEEDBACK_DIR/.outcomes"
PATTERNS_DIR="$FEEDBACK_DIR/.patterns"

# Create directories if needed
mkdir -p "$COUNTERS_DIR" "$OUTCOMES_DIR" "$PATTERNS_DIR"

# Thresholds (can be customized per agent)
DEFAULT_EXECUTION_THRESHOLD=10
DEFAULT_FAILURE_THRESHOLD=3
DEFAULT_PATTERN_THRESHOLD=3

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ============================================
# CORE FUNCTIONS
# ============================================

# Initialize agent profile
init_agent_profile() {
    local agent=$1
    local profile_file="$FEEDBACK_DIR/.profiles/${agent}.profile"

    if [ ! -f "$profile_file" ]; then
        mkdir -p "$(dirname "$profile_file")"
        cat > "$profile_file" << EOF
# Learning profile for $agent
EXECUTION_THRESHOLD=${DEFAULT_EXECUTION_THRESHOLD}
FAILURE_THRESHOLD=${DEFAULT_FAILURE_THRESHOLD}
PATTERN_THRESHOLD=${DEFAULT_PATTERN_THRESHOLD}
AUTO_FIX_ENABLED=false
LAST_UPDATE=$(date +%s)
EOF
    fi

    source "$profile_file"
}

# ============================================
# EXECUTION COUNTER TRIGGER
# ============================================

increment_execution_counter() {
    local agent=$1
    local counter_file="$COUNTERS_DIR/${agent}.count"

    # Get current count
    local current_count=$(cat "$counter_file" 2>/dev/null || echo 0)
    local new_count=$((current_count + 1))
    echo "$new_count" > "$counter_file"

    # Load agent profile
    init_agent_profile "$agent"

    # Check threshold
    if [ "$new_count" -ge "${EXECUTION_THRESHOLD:-10}" ]; then
        echo -e "${YELLOW}🔄 Execution threshold reached for $agent (${new_count}/${EXECUTION_THRESHOLD})${NC}"
        trigger_learning_analysis "$agent" "execution_threshold"
        echo "0" > "$counter_file"  # Reset counter
        return 0
    fi

    echo "Execution count: ${new_count}/${EXECUTION_THRESHOLD}"
    return 1
}

# ============================================
# FAILURE RATE TRIGGER
# ============================================

track_outcome() {
    local agent=$1
    local outcome=$2  # success, failure, partial_success
    local outcomes_file="$OUTCOMES_DIR/${agent}.recent"

    # Log outcome (keep last 10)
    echo "$outcome" >> "$outcomes_file"
    tail -10 "$outcomes_file" > "${outcomes_file}.tmp"
    mv "${outcomes_file}.tmp" "$outcomes_file"

    # Count recent failures
    local total=$(wc -l < "$outcomes_file" 2>/dev/null || echo 0)
    local failures=$(grep -c "failure" "$outcomes_file" 2>/dev/null || echo 0)
    local partials=$(grep -c "partial" "$outcomes_file" 2>/dev/null || echo 0)

    # Load agent profile
    init_agent_profile "$agent"

    # Check failure threshold (handle division safely)
    local partial_weight=0
    [ "$partials" -gt 0 ] && partial_weight=$((partials / 2))
    local problem_count=$((failures + partial_weight))
    if [ "$problem_count" -ge "${FAILURE_THRESHOLD:-3}" ]; then
        echo -e "${RED}⚠️ High failure rate for $agent (${problem_count}/${total} recent executions)${NC}"
        trigger_learning_analysis "$agent" "high_failure_rate"
        > "$outcomes_file"  # Clear recent outcomes after trigger
        return 0
    fi

    echo "Recent outcomes: $failures failures, $partials partial, from $total executions"
    return 1
}

# ============================================
# PATTERN DETECTION TRIGGER
# ============================================

detect_pattern() {
    local agent=$1
    local issue_type=$2
    local description="${3:-}"
    local patterns_file="$PATTERNS_DIR/${agent}.patterns"

    # Log the issue pattern
    echo "$(date +%s):$issue_type:$description" >> "$patterns_file"

    # Keep only recent patterns (last hour)
    local one_hour_ago=$(($(date +%s) - 3600))
    grep -v "^[0-9]*:" "$patterns_file" 2>/dev/null | \
        awk -F: "\$1 > $one_hour_ago" > "${patterns_file}.tmp"
    mv "${patterns_file}.tmp" "$patterns_file" 2>/dev/null || true

    # Count occurrences of this issue type
    local issue_count=$(grep -c ":${issue_type}:" "$patterns_file" 2>/dev/null || echo "0")

    # Load agent profile
    init_agent_profile "$agent"

    # Check pattern threshold
    if [ "$issue_count" -ge "${PATTERN_THRESHOLD:-3}" ]; then
        echo -e "${YELLOW}🔄 Pattern detected for $agent: '$issue_type' occurred $issue_count times${NC}"

        # Check for known fixes
        if has_known_fix "$issue_type"; then
            echo -e "${GREEN}💡 Applying known fix for: $issue_type${NC}"
            apply_known_fix "$agent" "$issue_type"
        else
            trigger_learning_analysis "$agent" "repeated_pattern:$issue_type"
        fi

        # Clear this pattern after addressing
        grep -v ":${issue_type}:" "$patterns_file" > "${patterns_file}.tmp" 2>/dev/null || true
        mv "${patterns_file}.tmp" "$patterns_file" 2>/dev/null || true
        return 0
    fi

    echo "Pattern count for '$issue_type': ${issue_count}/${PATTERN_THRESHOLD}"
    return 1
}

# ============================================
# KNOWN FIXES DATABASE
# ============================================

has_known_fix() {
    local issue_type=$1

    case "$issue_type" in
        "path_error"|"directory_not_found")
            return 0
            ;;
        "permission_denied")
            return 0
            ;;
        "timeout"|"slow_response")
            return 0
            ;;
        "git_error"|"merge_conflict")
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

apply_known_fix() {
    local agent=$1
    local issue_type=$2
    local agent_file="$LEARNING_HUB/.claude/agents/${agent}.md"

    echo "Applying fix for $issue_type to $agent..."

    # Backup agent file
    cp "$agent_file" "${agent_file}.backup.$(date +%Y%m%d_%H%M%S)"

    case "$issue_type" in
        "path_error"|"directory_not_found")
            # Add absolute path handling
            if ! grep -q "ALWAYS use absolute paths" "$agent_file"; then
                cat >> "$agent_file" << 'EOF'

## Applied Learning: Absolute Path Handling
# Auto-applied: $(date +%Y-%m-%d)
# Issue: path_error detected multiple times
# Solution: Always use absolute paths
WORK_DIR="$(realpath "${WORK_DIR:-$(pwd)}")"
cd "$WORK_DIR" || exit 1
EOF
                echo -e "${GREEN}✓ Applied absolute path fix${NC}"
            fi
            ;;

        "permission_denied")
            # Add permission checking
            if ! grep -q "Check permissions before" "$agent_file"; then
                cat >> "$agent_file" << 'EOF'

## Applied Learning: Permission Checking
# Auto-applied: $(date +%Y-%m-%d)
# Check permissions before file operations
[ -w "$target_file" ] || { echo "No write permission"; exit 1; }
EOF
                echo -e "${GREEN}✓ Applied permission check fix${NC}"
            fi
            ;;

        "timeout"|"slow_response")
            # Add timeout handling
            if ! grep -q "timeout.*handling" "$agent_file"; then
                cat >> "$agent_file" << 'EOF'

## Applied Learning: Timeout Handling
# Auto-applied: $(date +%Y-%m-%d)
# Add timeout and retry logic
MAX_RETRIES=3
TIMEOUT=30
for i in $(seq 1 $MAX_RETRIES); do
    if timeout $TIMEOUT command; then
        break
    fi
    echo "Retry $i/$MAX_RETRIES..."
done
EOF
                echo -e "${GREEN}✓ Applied timeout handling fix${NC}"
            fi
            ;;
    esac

    # Log the fix application
    echo '{
        "timestamp": "'$(date -Iseconds)'",
        "event": "auto_fix_applied",
        "agent": "'$agent'",
        "issue_type": "'$issue_type'",
        "fix": "known_pattern"
    }' >> "$FEEDBACK_DIR/logs/$(date +%Y-%m-%d)-learning-system.json"
}

# ============================================
# LEARNING ANALYSIS TRIGGER
# ============================================

trigger_learning_analysis() {
    local agent=$1
    local trigger_reason=$2

    echo -e "${BLUE}📊 Triggering learning analysis for $agent${NC}"
    echo "Reason: $trigger_reason"

    # Run performance analysis
    if python "$FEEDBACK_DIR/analyze_agent_performance.py" "$agent" \
           --days 7 --feedback-dir "$FEEDBACK_DIR" > "/tmp/${agent}_analysis.txt" 2>&1; then

        # Extract key findings
        local success_rate=$(grep "Success Rate:" "/tmp/${agent}_analysis.txt" | grep -o '[0-9.]*' | head -1)
        local top_issues=$(grep -A3 "Top Issue Types:" "/tmp/${agent}_analysis.txt")

        echo "Current success rate: ${success_rate}%"

        # Decide on action
        if (( $(echo "$success_rate < 70" | bc -l) )); then
            echo -e "${RED}Critical: Success rate below 70%${NC}"

            # Load profile to check auto-fix setting
            init_agent_profile "$agent"

            if [ "$AUTO_FIX_ENABLED" = "true" ]; then
                echo "Auto-fix enabled - applying improvements..."
                apply_automatic_improvements "$agent"
            else
                echo "Manual review required - creating learning report..."
                create_learning_report "$agent" "$trigger_reason"
            fi
        else
            echo "Performance acceptable - logging for trends"
        fi
    else
        echo -e "${RED}Analysis failed${NC}"
    fi

    # Update last analysis time
    touch "$FEEDBACK_DIR/.last_analysis_${agent}"
}

# ============================================
# AUTOMATIC IMPROVEMENT APPLICATION
# ============================================

apply_automatic_improvements() {
    local agent=$1

    echo "Analyzing patterns for automatic fixes..."

    # Extract patterns from recent logs
    local log_file="$FEEDBACK_DIR/logs/$(date +%Y-%m-%d)-${agent}.json"

    if [ -f "$log_file" ]; then
        # Count issue types
        local path_errors=$(grep -c '"type":"path_error"' "$log_file" 2>/dev/null || echo 0)
        local perm_errors=$(grep -c '"type":"permission"' "$log_file" 2>/dev/null || echo 0)
        local timeout_errors=$(grep -c '"type":"timeout"' "$log_file" 2>/dev/null || echo 0)

        # Apply fixes for detected patterns
        [ "$path_errors" -gt 2 ] && apply_known_fix "$agent" "path_error"
        [ "$perm_errors" -gt 2 ] && apply_known_fix "$agent" "permission_denied"
        [ "$timeout_errors" -gt 2 ] && apply_known_fix "$agent" "timeout"

        echo -e "${GREEN}✓ Automatic improvements applied${NC}"
    fi
}

# ============================================
# SESSION-END TRIGGER
# ============================================

session_end_analysis() {
    echo -e "${BLUE}📊 Running session-end learning analysis${NC}"

    # Check all agents that were active this session
    for log_file in "$FEEDBACK_DIR/logs/$(date +%Y-%m-%d)"-*.json; do
        [ -f "$log_file" ] || continue

        # Extract agent name from filename
        local agent=$(basename "$log_file" .json | cut -d- -f4)
        [ "$agent" = "learning" ] && continue  # Skip system logs

        echo "Checking $agent..."

        # Count events for this agent today
        local event_count=$(grep -c '"event"' "$log_file" 2>/dev/null || echo 0)

        if [ "$event_count" -gt 5 ]; then
            echo "  Active agent ($event_count events) - checking for improvements"

            # Check if learning analysis needed
            local last_analysis="$FEEDBACK_DIR/.last_analysis_${agent}"
            local hours_since=24

            if [ -f "$last_analysis" ]; then
                hours_since=$(( ($(date +%s) - $(stat -c %Y "$last_analysis" 2>/dev/null || echo 0)) / 3600 ))
            fi

            if [ "$hours_since" -ge 12 ]; then
                trigger_learning_analysis "$agent" "session_end"
            fi
        fi
    done

    echo -e "${GREEN}✓ Session-end analysis complete${NC}"
}

# ============================================
# LEARNING REPORT GENERATION
# ============================================

create_learning_report() {
    local agent=$1
    local trigger_reason=$2
    local report_file="$FEEDBACK_DIR/learnings/${agent}-report-$(date +%Y%m%d_%H%M%S).md"

    cat > "$report_file" << EOF
# Learning Report: $agent
Generated: $(date +%Y-%m-%d %H:%M:%S)
Trigger: $trigger_reason

## Performance Summary
$(grep -A10 "Executive Summary" "/tmp/${agent}_analysis.txt" 2>/dev/null || echo "Analysis not available")

## Recommended Actions

### Immediate Fixes
EOF

    # Add specific recommendations based on issues
    if grep -q "path_error" "/tmp/${agent}_analysis.txt" 2>/dev/null; then
        echo "- [ ] Add absolute path handling" >> "$report_file"
    fi

    if grep -q "permission" "/tmp/${agent}_analysis.txt" 2>/dev/null; then
        echo "- [ ] Add permission checking" >> "$report_file"
    fi

    cat >> "$report_file" << EOF

### Review Required
- [ ] Check agent file for outdated patterns
- [ ] Update error handling based on failures
- [ ] Consider enabling AUTO_FIX_ENABLED in profile

## Command to Apply Fixes
\`\`\`bash
$FEEDBACK_DIR/apply_learnings.sh apply $agent
\`\`\`
EOF

    echo -e "${GREEN}Learning report created: $report_file${NC}"
}

# ============================================
# MAIN EVENT HANDLER
# ============================================

handle_agent_event() {
    local event_type=$1
    local agent=$2
    shift 2
    local args="$@"

    case "$event_type" in
        "execution_start")
            increment_execution_counter "$agent"
            ;;

        "execution_complete")
            local outcome=${1:-success}
            track_outcome "$agent" "$outcome"
            ;;

        "issue_detected")
            local issue_type=$1
            local description=${2:-}
            detect_pattern "$agent" "$issue_type" "$description"
            ;;

        "session_end")
            session_end_analysis
            ;;

        "check_agent")
            # Manual check for specific agent
            echo "Checking $agent status..."
            increment_execution_counter "$agent" || true
            track_outcome "$agent" "check" || true
            ;;

        *)
            echo "Unknown event type: $event_type"
            echo "Usage: $0 <event_type> <agent> [args...]"
            echo ""
            echo "Event types:"
            echo "  execution_start <agent>     - Track execution start"
            echo "  execution_complete <agent> <outcome> - Track completion"
            echo "  issue_detected <agent> <type> [desc] - Log issue pattern"
            echo "  session_end                 - Run session-end analysis"
            echo "  check_agent <agent>         - Manual status check"
            return 1
            ;;
    esac
}

# ============================================
# ADAPTIVE THRESHOLD ADJUSTMENT
# ============================================

adjust_thresholds() {
    local agent=$1
    local profile_file="$FEEDBACK_DIR/.profiles/${agent}.profile"

    # Load current profile
    init_agent_profile "$agent"

    # Get recent performance
    local success_rate=$(python "$FEEDBACK_DIR/analyze_agent_performance.py" "$agent" \
                        --days 7 --feedback-dir "$FEEDBACK_DIR" 2>/dev/null | \
                        grep "Success Rate:" | grep -o '[0-9.]*' | head -1)

    if [ -n "$success_rate" ]; then
        echo "Adjusting thresholds based on ${success_rate}% success rate..."

        # More frequent checks for struggling agents
        if (( $(echo "$success_rate < 70" | bc -l) )); then
            EXECUTION_THRESHOLD=5
            FAILURE_THRESHOLD=2
            echo "  Lowered thresholds for faster response"
        # Less frequent for stable agents
        elif (( $(echo "$success_rate > 90" | bc -l) )); then
            EXECUTION_THRESHOLD=20
            FAILURE_THRESHOLD=5
            echo "  Raised thresholds for stable agent"
        fi

        # Save updated profile
        cat > "$profile_file" << EOF
# Learning profile for $agent (auto-adjusted)
EXECUTION_THRESHOLD=${EXECUTION_THRESHOLD}
FAILURE_THRESHOLD=${FAILURE_THRESHOLD}
PATTERN_THRESHOLD=${PATTERN_THRESHOLD}
AUTO_FIX_ENABLED=${AUTO_FIX_ENABLED}
LAST_UPDATE=$(date +%s)
SUCCESS_RATE=$success_rate
EOF
    fi
}

# ============================================
# ENTRY POINT
# ============================================

# If sourced, export functions for use in agents
if [ "${BASH_SOURCE[0]}" != "${0}" ]; then
    export -f handle_agent_event
    export -f increment_execution_counter
    export -f track_outcome
    export -f detect_pattern
    export -f session_end_analysis
    echo "Event-driven learning functions loaded"
else
    # If executed directly, handle the event
    handle_agent_event "$@"
fi
