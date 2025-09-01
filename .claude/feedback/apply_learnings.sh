#!/bin/bash

# Apply Learnings Script
# Automates the process of converting feedback into agent updates

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FEEDBACK_DIR="${CLAUDE_FEEDBACK_DIR:-$SCRIPT_DIR}"
LEARNING_HUB="${CLAUDE_LEARNING_HUB:-$(dirname $(dirname $SCRIPT_DIR))}"
AGENTS_DIR="$LEARNING_HUB/.claude/agents"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "🧠 Agent Learning Application System"
echo "======================================"
echo "Learning Hub: $LEARNING_HUB"
echo "Feedback Dir: $FEEDBACK_DIR"
echo ""

# Function to analyze recent issues
analyze_recent_issues() {
    local agent=$1
    local days=${2:-7}

    echo "📊 Analyzing $agent (last $days days)..."

    # Run Python analysis
    if python "$FEEDBACK_DIR/analyze_agent_performance.py" "$agent" --days "$days" --feedback-dir "$FEEDBACK_DIR" > /tmp/agent_analysis.txt 2>&1; then
        # Extract key metrics
        local success_rate=$(grep "Success Rate:" /tmp/agent_analysis.txt | grep -o '[0-9.]*' | head -1)
        local issues=$(grep "Total Issues:" /tmp/agent_analysis.txt | grep -o '[0-9]*' | head -1)

        echo "  Success Rate: ${success_rate}%"
        echo "  Total Issues: $issues"

        # Return 1 if needs update (success rate < 80% or issues > 5)
        if (( $(echo "$success_rate < 80" | bc -l) )) || [ "$issues" -gt 5 ]; then
            return 1
        fi
    else
        echo "  ⚠️ Analysis failed"
    fi

    return 0
}

# Function to extract patterns from logs
extract_patterns() {
    local agent=$1
    local pattern_file="$FEEDBACK_DIR/learnings/${agent}-patterns-$(date +%Y%m%d).md"

    echo "🔍 Extracting patterns for $agent..."

    # Create patterns file
    cat > "$pattern_file" << EOF
# Patterns Extracted for $agent
Date: $(date +%Y-%m-%d)

## Repeated Issues
EOF

    # Find repeated issues (simplified - in practice would be more sophisticated)
    local log_file="$FEEDBACK_DIR/logs/$(date +%Y-%m-%d)-${agent}.json"
    if [ -f "$log_file" ]; then
        # Count issue types
        grep '"type":' "$log_file" 2>/dev/null | sort | uniq -c | sort -rn | head -5 >> "$pattern_file"
    fi

    echo "" >> "$pattern_file"
    echo "## Suggested Fixes" >> "$pattern_file"

    # Add context-specific suggestions
    if grep -q "path.*error" "$log_file" 2>/dev/null; then
        echo "- Always use absolute paths" >> "$pattern_file"
    fi

    if grep -q "permission" "$log_file" 2>/dev/null; then
        echo "- Add permission checks before file operations" >> "$pattern_file"
    fi

    if grep -q "timeout" "$log_file" 2>/dev/null; then
        echo "- Implement timeout handling with retries" >> "$pattern_file"
    fi

    echo "  Patterns saved to: $pattern_file"
}

# Function to update agent with learnings
apply_learning_to_agent() {
    local agent=$1
    local learning=$2
    local agent_file="$AGENTS_DIR/${agent}.md"

    echo "📝 Applying learning to $agent..."

    # Backup agent file
    cp "$agent_file" "${agent_file}.backup.$(date +%Y%m%d_%H%M%S)"

    # Check if learning section exists
    if ! grep -q "## Applied Learnings" "$agent_file"; then
        # Add learning section before the last line
        echo "" >> "$agent_file"
        echo "## Applied Learnings" >> "$agent_file"
        echo "" >> "$agent_file"
    fi

    # Add learning with timestamp
    echo "" >> "$agent_file"
    echo "### Learning Applied: $(date +%Y-%m-%d)" >> "$agent_file"
    echo "$learning" >> "$agent_file"

    # Update version number if present
    if grep -q "AGENT_VERSION=" "$agent_file"; then
        # Increment patch version
        current_version=$(grep "AGENT_VERSION=" "$agent_file" | grep -o '[0-9.]*' | head -1)
        IFS='.' read -r major minor patch <<< "$current_version"
        new_version="$major.$minor.$((patch + 1))"
        sed -i "s/AGENT_VERSION=\"$current_version\"/AGENT_VERSION=\"$new_version\"/" "$agent_file"
        echo "  Version updated: $current_version -> $new_version"
    fi

    echo -e "  ${GREEN}✓ Learning applied successfully${NC}"
}

# Function to test agent after update
test_agent_update() {
    local agent=$1

    echo "🧪 Testing $agent after update..."

    # Simple validation - check syntax
    if grep -q "^---$" "$AGENTS_DIR/${agent}.md"; then
        echo -e "  ${GREEN}✓ Agent file valid${NC}"
        return 0
    else
        echo -e "  ${RED}✗ Agent file may be corrupted${NC}"
        return 1
    fi
}

# Main workflow
main() {
    local mode=${1:-check}  # check, apply, or auto

    case $mode in
        check)
            echo "🔍 Checking agents for needed updates..."
            echo ""

            for agent_file in "$AGENTS_DIR"/*.md; do
                [ -f "$agent_file" ] || continue
                agent=$(basename "$agent_file" .md)

                # Skip templates and special files
                [[ "$agent" == "TEMPLATE"* ]] && continue
                [[ "$agent" == "README"* ]] && continue

                if ! analyze_recent_issues "$agent" 7; then
                    echo -e "  ${YELLOW}⚠️ $agent needs attention${NC}"
                    echo ""
                fi
            done
            ;;

        apply)
            local agent=${2:-}
            if [ -z "$agent" ]; then
                echo -e "${RED}Error: Agent name required for apply mode${NC}"
                echo "Usage: $0 apply <agent-name>"
                exit 1
            fi

            echo "📋 Applying learnings to $agent..."
            echo ""

            # Extract patterns
            extract_patterns "$agent"

            # Read the latest learning
            local latest_learning=$(tail -5 "$FEEDBACK_DIR/learnings/${agent}-patterns-"*.md 2>/dev/null | head -5)

            if [ -n "$latest_learning" ]; then
                # Apply to agent
                apply_learning_to_agent "$agent" "$latest_learning"

                # Test the update
                if test_agent_update "$agent"; then
                    echo -e "${GREEN}✅ Agent successfully updated with learnings${NC}"
                else
                    echo -e "${RED}❌ Update failed - restoring backup${NC}"
                    # Restore from backup
                    latest_backup=$(ls -t "$AGENTS_DIR/${agent}.md.backup."* | head -1)
                    cp "$latest_backup" "$AGENTS_DIR/${agent}.md"
                fi
            else
                echo "No learnings found to apply"
            fi
            ;;

        auto)
            echo "🤖 Automatic learning mode"
            echo ""

            # Check all agents and apply learnings if needed
            for agent_file in "$AGENTS_DIR"/*.md; do
                [ -f "$agent_file" ] || continue
                agent=$(basename "$agent_file" .md)

                # Skip templates
                [[ "$agent" == "TEMPLATE"* ]] && continue
                [[ "$agent" == "README"* ]] && continue

                if ! analyze_recent_issues "$agent" 7; then
                    echo "🔧 Auto-updating $agent..."
                    extract_patterns "$agent"

                    # Simple auto-fix for common issues
                    if grep -q "path.*error" "$FEEDBACK_DIR/logs/"*"-${agent}.json" 2>/dev/null; then
                        learning="- Added: Always use absolute paths for directory operations"
                        apply_learning_to_agent "$agent" "$learning"
                    fi

                    echo ""
                fi
            done

            echo -e "${GREEN}✅ Automatic learning cycle complete${NC}"
            ;;

        *)
            echo "Usage: $0 {check|apply <agent>|auto}"
            echo ""
            echo "  check       - Check which agents need updates"
            echo "  apply       - Apply learnings to specific agent"
            echo "  auto        - Automatically apply learnings to all agents"
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
