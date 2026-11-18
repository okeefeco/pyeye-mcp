#!/bin/bash
# Wrapper script to track grep usage for dogfooding metrics

# Path to the dogfooding metrics script
DOGFOODING_SCRIPT="$(dirname "$0")/dogfooding_metrics.py"
# Its imports live only in the project's uv environment (#879)
PROJECT_ROOT="$(dirname "$0")/.."

# Function to log grep usage
log_grep_usage() {
    if [[ -f "$DOGFOODING_SCRIPT" ]]; then
        uv run --frozen --project "$PROJECT_ROOT" python "$DOGFOODING_SCRIPT" grep 2>/dev/null || true
    fi
}

# Check if this is a grep command that should be tracked
should_track() {
    local cmd="$1"
    shift

    # Track grep/egrep/fgrep/rg commands with code search patterns
    case "$cmd" in
        grep|egrep|fgrep|rg)
            # Look for patterns that suggest code search
            for arg in "$@"; do
                case "$arg" in
                    # Common code search patterns
                    *class*|*def*|*function*|*import*|*from*|*.py|*.js|*.ts|*.java|*.c|*.cpp)
                        return 0
                        ;;
                    # Recursive or file-type searches
                    -r|-R|--recursive|--type=*|--include=*)
                        return 0
                        ;;
                esac
            done
            ;;
    esac

    return 1
}

# Main execution
COMMAND=$(basename "$0")
ORIGINAL_CMD="/usr/bin/$COMMAND"

# Check if we should track this command
if should_track "$COMMAND" "$@"; then
    log_grep_usage
fi

# Execute the original command
if [[ -x "$ORIGINAL_CMD" ]]; then
    exec "$ORIGINAL_CMD" "$@"
else
    # Fallback to PATH
    exec "$COMMAND" "$@"
fi
