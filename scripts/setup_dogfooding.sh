#!/bin/bash
# Complete setup for dogfooding metrics automation

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🐕 Setting up Python Code Intelligence MCP Dogfooding Metrics"
echo "======================================================================"
echo ""

# Check prerequisites
echo "📋 Checking prerequisites..."

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed"
    exit 1
fi

if ! command -v git &> /dev/null; then
    echo "❌ Git is required but not installed"
    exit 1
fi

if [[ ! -f "$PROJECT_ROOT/scripts/dogfooding_metrics.py" ]]; then
    echo "❌ Dogfooding metrics script not found"
    echo "   Make sure you're running this from the project root"
    exit 1
fi

echo "✅ Prerequisites check passed"
echo ""

# Install git hooks
echo "🪝 Installing git hooks..."
bash "$SCRIPT_DIR/install_hooks.sh"
echo ""

# Setup shell aliases
echo "🔗 Setting up shell aliases..."
bash "$SCRIPT_DIR/setup_aliases.sh"
echo ""

# Setup grep tracking
echo "🔍 Setting up grep usage tracking..."
bash "$SCRIPT_DIR/setup_grep_tracking.sh"
echo ""

# Create metrics directory
echo "📁 Creating metrics directory..."
mkdir -p "$HOME/.pycodemcp/metrics"
echo "✅ Metrics directory created: $HOME/.pycodemcp/metrics"
echo ""

# Test the setup
echo "🧪 Testing setup..."

# Test metrics script
if python "$PROJECT_ROOT/scripts/dogfooding_metrics.py" --help &> /dev/null; then
    echo "✅ Dogfooding metrics script works"
else
    echo "❌ Dogfooding metrics script failed"
    exit 1
fi

# Test git hooks (handle worktrees)
if [[ -f "$PROJECT_ROOT/.git" ]]; then
    GIT_DIR=$(grep "gitdir:" "$PROJECT_ROOT/.git" | cut -d' ' -f2)
    if [[ ! "$GIT_DIR" = /* ]]; then
        GIT_DIR="$PROJECT_ROOT/$GIT_DIR"
    fi
    HOOKS_DIR="$GIT_DIR/hooks"
else
    HOOKS_DIR="$PROJECT_ROOT/.git/hooks"
fi

if [[ -x "$HOOKS_DIR/post-checkout" ]]; then
    echo "✅ Git hooks installed and executable"
else
    echo "❌ Git hooks not properly installed"
    exit 1
fi

echo ""
echo "🎉 Dogfooding metrics setup complete!"
echo ""
echo "📊 What happens now:"
echo "   1. When you switch branches: Auto-starts metrics session"
echo "   2. When you use 'grep': Auto-tracks manual search usage"
echo "   3. When you commit: Auto-ends session and shows stats"
echo "   4. MCP tool usage: Automatically tracked via server"
echo ""
echo "🔄 To activate shell aliases:"
echo "   source ~/.bashrc  # or ~/.zshrc"
echo ""
echo "🚀 Quick commands:"
echo "   mcp-start         # Manually start session"
echo "   mcp-end           # Manually end session"
echo "   mcp-report        # Generate weekly report"
echo "   mcp-saved 10 'reason'  # Log time saved"
echo "   mcp-bug 'description'  # Log prevented bug"
echo ""
echo "📈 To see your metrics:"
echo "   python scripts/dogfooding_metrics.py report --days 7"
echo ""
echo "Happy dogfooding! 🐕‍🦺"
