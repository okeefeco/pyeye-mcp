#!/bin/bash
# Setup shell aliases for automatic dogfooding metrics tracking

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Detect shell
if [[ -n "$ZSH_VERSION" ]]; then
    SHELL_RC="$HOME/.zshrc"
    SHELL_NAME="zsh"
elif [[ -n "$BASH_VERSION" ]]; then
    SHELL_RC="$HOME/.bashrc"
    SHELL_NAME="bash"
else
    echo "❌ Unsupported shell. Please add aliases manually."
    exit 1
fi

echo "📊 Setting up dogfooding metrics aliases for $SHELL_NAME..."

# Check if aliases already exist
if grep -q "# Dogfooding Metrics Aliases" "$SHELL_RC" 2>/dev/null; then
    echo "⚠️  Aliases already exist in $SHELL_RC"
    echo "Remove existing aliases before re-running this script."
    exit 1
fi

# Add aliases to shell rc file
cat >> "$SHELL_RC" << EOF

# Dogfooding Metrics Aliases - Added by $(date)
# Auto-track grep usage for PyEye dogfooding

# Track grep usage automatically
function tracked_grep() {
    # Only track if we're in a project with dogfooding metrics
    if [[ -f "scripts/dogfooding_metrics.py" ]]; then
        python scripts/dogfooding_metrics.py grep 2>/dev/null || true
    fi
    command grep "\$@"
}
alias grep='tracked_grep'

# Quick commands for metrics
alias mcp-start='python scripts/dogfooding_metrics.py start'
alias mcp-end='python scripts/dogfooding_metrics.py end'
alias mcp-report='python scripts/dogfooding_metrics.py report'
alias mcp-saved='python scripts/dogfooding_metrics.py saved'
alias mcp-bug='python scripts/dogfooding_metrics.py bug'

# Auto-start metrics when cd'ing into project
function mcp_cd() {
    builtin cd "\$@"
    # Auto-start session if we enter a project with dogfooding metrics
    if [[ -f "scripts/dogfooding_metrics.py" ]] && [[ ! -f "\$HOME/.pyeye/metrics/current_session.json" ]]; then
        # Extract issue number from current branch
        local branch=\$(git branch --show-current 2>/dev/null || echo "")
        local issue=\$(echo "\$branch" | grep -oE '[0-9]+' | head -1)
        if [[ -n "\$issue" ]]; then
            echo "📊 Auto-starting dogfooding metrics for issue #\$issue..."
            python scripts/dogfooding_metrics.py start --issue "\$issue" 2>/dev/null || true
        fi
    fi
}
alias cd='mcp_cd'

# End of Dogfooding Metrics Aliases
EOF

echo "✅ Aliases added to $SHELL_RC"
echo ""
echo "Added aliases:"
echo "  - grep: Automatically tracks usage in dogfooding projects"
echo "  - cd: Auto-starts metrics session when entering project"
echo "  - mcp-start, mcp-end, mcp-report: Quick metric commands"
echo ""
echo "To activate: source $SHELL_RC"
echo "Or restart your terminal"
