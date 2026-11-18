#!/bin/bash
# Track grep usage for dogfooding metrics, then run the real command.
#
# Called by the wrappers setup_grep_tracking.sh installs in ~/.local/bin:
#   exec grep_tracker.sh <command> <args...>
# The command comes from the first argument (#969): it used to come from
# basename "$0", which is this script's own name, so nothing was counted and
# the wrapped command itself failed with "not found".

# The marker every generated wrapper carries on its second line
WRAPPER_MARKER="# Auto-generated grep tracker wrapper for dogfooding metrics"

# Path to the dogfooding metrics script
DOGFOODING_SCRIPT="$(dirname "$0")/dogfooding_metrics.py"
# Its imports live only in the project's uv environment (#879)
PROJECT_ROOT="$(dirname "$0")/.."

# Function to log grep usage
log_grep_usage() {
    if [[ -f "$DOGFOODING_SCRIPT" ]]; then
        uv run --frozen --project "$PROJECT_ROOT" python "$DOGFOODING_SCRIPT" grep >/dev/null 2>&1 || true
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

# Is $1 one of our generated wrappers? Read with bash builtins: grep may be one.
is_wrapper() {
    local first="" second=""
    { IFS= read -r first; IFS= read -r second; } < "$1" 2>/dev/null || true
    [[ "$second" == "$WRAPPER_MARKER" ]]
}

# The real command: the first one on PATH that isn't a wrapper (so a wrapper
# can never exec itself, whether it was generated before or after #969)
find_real_command() {
    local cmd="$1" dir candidate
    local IFS=:
    for dir in $PATH; do
        candidate="${dir:-.}/$cmd"
        if [[ -f "$candidate" && -x "$candidate" ]] && ! is_wrapper "$candidate"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

# Main execution
COMMAND="$1"
shift

if [[ -z "$COMMAND" ]]; then
    echo "grep_tracker.sh: usage: grep_tracker.sh <command> [args...]" >&2
    exit 2
fi

# Check if we should track this command
if should_track "$COMMAND" "$@"; then
    log_grep_usage
fi

# Execute the original command
if ! REAL_CMD="$(find_real_command "$COMMAND")"; then
    echo "grep_tracker.sh: $COMMAND: not found on PATH (outside the tracker wrappers)" >&2
    exit 127
fi
exec "$REAL_CMD" "$@"
