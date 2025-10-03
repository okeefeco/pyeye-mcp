#!/bin/bash
# Worktree Helper Functions for Claude Sessions
# Source this file to get helpful worktree management functions

# Store startup context
export CLAUDE_STARTUP_DIR="${CLAUDE_STARTUP_DIR:-$(pwd)}"
export CLAUDE_WORKING_DIR="${CLAUDE_WORKING_DIR:-$(pwd)}"

# Function to switch worktree and maintain context
switch_worktree() {
    local target="$1"

    if [ -z "$target" ]; then
        echo "Usage: switch_worktree <path-or-issue-number>"
        return 1
    fi

    # If numeric, find worktree for that issue
    if [[ "$target" =~ ^[0-9]+$ ]]; then
        local issue_num="$target"
        local worktree_path=$(git worktree list | grep -E "/(feat|fix|docs|test|chore|perf|refactor|style|build|ci)-${issue_num}-" | awk '{print $1}' | head -1)

        if [ -z "$worktree_path" ]; then
            echo "No worktree found for issue $issue_num"
            echo "Available worktrees:"
            git worktree list
            return 1
        fi

        target="$worktree_path"
    fi

    # Switch to the worktree
    if cd "$target" 2>/dev/null; then
        export CLAUDE_WORKING_DIR=$(pwd)
        echo "✅ Switched to: $CLAUDE_WORKING_DIR"
        echo "📁 Claude home: $CLAUDE_STARTUP_DIR"
        echo "🌿 Branch: $(git branch --show-current)"
        git status --short
    else
        echo "❌ Failed to switch to: $target"
        return 1
    fi
}

# Function to run commands in working directory
in_work() {
    (cd "$CLAUDE_WORKING_DIR" && "$@")
}

# Function to create worktree and switch to it
create_worktree() {
    local issue_num="$1"
    local type="${2:-fix}"
    local desc="$3"

    if [ -z "$issue_num" ] || [ -z "$desc" ]; then
        echo "Usage: create_worktree <issue-number> [type] <description>"
        echo "Types: feat, fix, docs, test, chore, perf, refactor, style, build, ci"
        return 1
    fi

    local branch_name="$type/$issue_num-$desc"
    local worktree_dir="../pyeye-mcp-work/$type-$issue_num-$desc"

    # Update main first
    echo "📥 Updating main branch..."
    (cd "$(git worktree list | head -1 | awk '{print $1}')" && git pull origin main)

    # Create worktree
    echo "🌲 Creating worktree: $worktree_dir"
    git worktree add "$worktree_dir" -b "$branch_name" main

    # Switch to it
    switch_worktree "$worktree_dir"

    # Set up environment
    echo "📦 Setting up environment..."
    uv venv && uv pip install -e ".[dev]"

    echo "✅ Worktree ready for issue #$issue_num"
}

# Show current context
show_context() {
    echo "🏠 Claude home: $CLAUDE_STARTUP_DIR"
    echo "📂 Working dir: $CLAUDE_WORKING_DIR"
    echo "🌿 Current branch: $(git branch --show-current 2>/dev/null || echo 'not in git repo')"
    echo ""
    echo "📍 Worktrees:"
    git worktree list
}

# Aliases for common operations that maintain context
alias gst='in_work git status'
alias gd='in_work git diff'
alias ga='in_work git add'
alias gc='in_work git commit'
alias pytest='in_work uv run pytest'
alias mypy='in_work uv run mypy'

echo "🔧 Worktree helper loaded. Available commands:"
echo "  switch_worktree <path-or-issue>  - Switch to a worktree"
echo "  create_worktree <issue> [type] <desc>  - Create and switch to new worktree"
echo "  show_context  - Show current context"
echo "  in_work <command>  - Run command in working directory"
echo ""
echo "Aliases available: gst, gd, ga, gc, pytest, mypy"
