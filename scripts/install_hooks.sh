#!/bin/bash
# Install git hooks for automatic dogfooding metrics tracking

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Handle git worktrees (where .git is a file pointing to the real git dir)
if [[ -f "$PROJECT_ROOT/.git" ]]; then
    GIT_DIR=$(grep "gitdir:" "$PROJECT_ROOT/.git" | cut -d' ' -f2)
    # Handle relative paths
    if [[ ! "$GIT_DIR" = /* ]]; then
        GIT_DIR="$PROJECT_ROOT/$GIT_DIR"
    fi
    GIT_HOOKS_DIR="$GIT_DIR/hooks"
else
    GIT_HOOKS_DIR="$PROJECT_ROOT/.git/hooks"
fi

# Create hooks directory if it doesn't exist
mkdir -p "$GIT_HOOKS_DIR"

echo "📊 Installing dogfooding metrics git hooks..."

# Create post-checkout hook (triggered when switching branches)
cat > "$GIT_HOOKS_DIR/post-checkout" << 'EOF'
#!/bin/bash
# Auto-start metrics session when switching branches

# Extract issue number from branch name (e.g., feat/135-description -> 135)
BRANCH=$(git branch --show-current)
ISSUE=$(echo "$BRANCH" | grep -oE '[0-9]+' | head -1)

# Only start session if we have dogfooding metrics and an issue number
if [[ -f "scripts/dogfooding_metrics.py" ]] && [[ -n "$ISSUE" ]]; then
    echo "📊 Starting dogfooding metrics for issue #$ISSUE..."
    python scripts/dogfooding_metrics.py start --issue "$ISSUE" 2>/dev/null || true
fi
EOF

# Create pre-commit hook (triggered before commit)
cat > "$GIT_HOOKS_DIR/pre-commit" << 'EOF'
#!/bin/bash
# Auto-end metrics session before commit

# Only end session if we have dogfooding metrics
if [[ -f "scripts/dogfooding_metrics.py" ]]; then
    # Check if there's an active session
    if [[ -f "$HOME/.pycodemcp/metrics/current_session.json" ]]; then
        echo "📊 Ending dogfooding metrics session..."
        python scripts/dogfooding_metrics.py end 2>/dev/null || true
    fi
fi

# Continue with other pre-commit hooks
if [[ -f ".git/hooks/pre-commit.sample" ]]; then
    .git/hooks/pre-commit.sample "$@"
fi
EOF

# Create prepare-commit-msg hook (add metrics to commit message)
cat > "$GIT_HOOKS_DIR/prepare-commit-msg" << 'EOF'
#!/bin/bash
# Add metrics summary to commit message

COMMIT_MSG_FILE=$1
COMMIT_SOURCE=$2

# Only add metrics for non-merge commits
if [[ -z "$COMMIT_SOURCE" ]] && [[ -f "$HOME/.pycodemcp/metrics/last_session_stats.json" ]]; then
    # Read the last session stats
    if command -v jq &> /dev/null; then
        MCP_RATIO=$(jq -r '.mcp_ratio' "$HOME/.pycodemcp/metrics/last_session_stats.json" 2>/dev/null || echo "0")
        TIME_SAVED=$(jq -r '.time_saved_minutes' "$HOME/.pycodemcp/metrics/last_session_stats.json" 2>/dev/null || echo "0")

        # Add metrics comment to commit message (comments are stripped before commit)
        echo "" >> "$COMMIT_MSG_FILE"
        echo "# Dogfooding Metrics:" >> "$COMMIT_MSG_FILE"
        echo "# - MCP adoption: ${MCP_RATIO}%" >> "$COMMIT_MSG_FILE"
        echo "# - Time saved: ${TIME_SAVED} minutes" >> "$COMMIT_MSG_FILE"
    fi
fi
EOF

# Make all hooks executable
chmod +x "$GIT_HOOKS_DIR/post-checkout"
chmod +x "$GIT_HOOKS_DIR/pre-commit"
chmod +x "$GIT_HOOKS_DIR/prepare-commit-msg"

echo "✅ Git hooks installed successfully!"
echo ""
echo "Hooks installed:"
echo "  - post-checkout: Auto-starts metrics session when switching branches"
echo "  - pre-commit: Auto-ends metrics session before commit"
echo "  - prepare-commit-msg: Adds metrics summary to commit messages"
echo ""
echo "To test: Switch branches or make a commit"
