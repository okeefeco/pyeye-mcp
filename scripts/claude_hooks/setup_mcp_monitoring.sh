#!/bin/bash
# Setup script for MCP monitoring hooks in Claude Code

set -e

echo "================================================"
echo "MCP Monitoring Setup for Claude Code"
echo "================================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Check if running from correct location
if [[ ! -f "$REPO_ROOT/pyproject.toml" ]] || [[ ! -d "$REPO_ROOT/src/pyeye" ]]; then
    echo -e "${RED}Error: This script must be run from the pyeye-mcp repository${NC}"
    exit 1
fi

echo "📁 Repository root: $REPO_ROOT"
echo ""

# Step 1: Create monitoring directory
echo "1️⃣  Creating monitoring directory..."
MONITORING_DIR="$HOME/.claude/mcp_monitoring"
mkdir -p "$MONITORING_DIR"
echo -e "${GREEN}✓${NC} Created: $MONITORING_DIR"
echo ""

# Step 2: Make Python scripts executable
echo "2️⃣  Making Python scripts executable..."
chmod +x "$SCRIPT_DIR"/*.py
echo -e "${GREEN}✓${NC} Scripts made executable"
echo ""

# Step 3: Install hooks configuration to Claude settings
echo "3️⃣  Installing hooks configuration..."
CLAUDE_SETTINGS_DIR="$HOME/.claude"
mkdir -p "$CLAUDE_SETTINGS_DIR"

# Check if settings.json already exists
if [[ -f "$CLAUDE_SETTINGS_DIR/settings.json" ]]; then
    echo -e "${YELLOW}⚠️  Existing settings.json found${NC}"
    echo "   Backing up to: settings.json.backup-$(date +%Y%m%d-%H%M%S)"
    cp "$CLAUDE_SETTINGS_DIR/settings.json" "$CLAUDE_SETTINGS_DIR/settings.json.backup-$(date +%Y%m%d-%H%M%S)"

    # Extract existing settings (non-hooks)
    if command -v jq &> /dev/null; then
        # If jq is available, merge properly
        EXISTING_SETTINGS=$(jq 'del(.hooks)' "$CLAUDE_SETTINGS_DIR/settings.json" 2>/dev/null || echo '{}')
        HOOKS_CONFIG=$(sed "s|~/GitHub/pyeye-mcp|$REPO_ROOT|g" "$SCRIPT_DIR/hooks.json")
        echo "$EXISTING_SETTINGS" | jq --argjson hooks "$HOOKS_CONFIG" '. + $hooks' > "$CLAUDE_SETTINGS_DIR/settings.json"
    else
        # Manual merge - just replace for now
        echo -e "${YELLOW}⚠️  jq not found - replacing settings.json (backup created)${NC}"
        sed "s|~/GitHub/pyeye-mcp|$REPO_ROOT|g" \
            "$SCRIPT_DIR/hooks.json" > "$CLAUDE_SETTINGS_DIR/settings.json"
    fi
else
    # No existing settings, just copy our hooks
    sed "s|~/GitHub/pyeye-mcp|$REPO_ROOT|g" \
        "$SCRIPT_DIR/hooks.json" > "$CLAUDE_SETTINGS_DIR/settings.json"
fi

echo -e "${GREEN}✓${NC} Installed: $CLAUDE_SETTINGS_DIR/settings.json"
echo ""

# Step 4: Create initial CSV headers
echo "4️⃣  Initializing data files..."
if [[ ! -f "$MONITORING_DIR/mcp_calls.csv" ]]; then
    echo "timestamp,session_id,tool,stage" > "$MONITORING_DIR/mcp_calls.csv"
    echo -e "${GREEN}✓${NC} Created: mcp_calls.csv"
fi

if [[ ! -f "$MONITORING_DIR/grep_usage.csv" ]]; then
    echo "timestamp,session_id,tool,context" > "$MONITORING_DIR/grep_usage.csv"
    echo -e "${GREEN}✓${NC} Created: grep_usage.csv"
fi

if [[ ! -f "$MONITORING_DIR/mcp_success.csv" ]]; then
    echo "timestamp,session_id,tool,status,response_size" > "$MONITORING_DIR/mcp_success.csv"
    echo -e "${GREEN}✓${NC} Created: mcp_success.csv"
fi
echo ""

# Step 5: Create convenience aliases
echo "5️⃣  Setting up convenience commands..."
ALIAS_FILE="$HOME/.claude/mcp_monitoring/aliases.sh"
cat > "$ALIAS_FILE" << 'EOF'
# MCP Monitoring Aliases
alias mcp-report='python3 $REPO_ROOT/scripts/claude_hooks/mcp_analytics.py'
alias mcp-report-week='python3 $REPO_ROOT/scripts/claude_hooks/mcp_analytics.py --days 7'
alias mcp-report-month='python3 $REPO_ROOT/scripts/claude_hooks/mcp_analytics.py --days 30'
alias mcp-export='python3 $REPO_ROOT/scripts/claude_hooks/mcp_analytics.py --export'
alias mcp-logs='tail -f ~/.claude/mcp_monitoring/*.csv'
alias mcp-errors='tail -f ~/.claude/mcp_monitoring/hook_errors.log'
alias mcp-session='cat ~/.claude/mcp_monitoring/active_session.json 2>/dev/null || echo "No active session"'
EOF

# Replace $REPO_ROOT in aliases
sed -i "s|\$REPO_ROOT|$REPO_ROOT|g" "$ALIAS_FILE"

echo -e "${GREEN}✓${NC} Created alias file: $ALIAS_FILE"
echo ""

# Step 6: Test hook configuration
echo "6️⃣  Testing hook configuration..."
if command -v claude &> /dev/null; then
    echo "   Testing PreToolUse hook for MCP tools..."
    # This would test the hook but claude CLI might not have a test command
    echo -e "${YELLOW}⚠️  Manual test required - run: claude code hook test PreToolUse mcp__pyeye__find_symbol${NC}"
else
    echo -e "${YELLOW}⚠️  Claude CLI not found in PATH - skipping hook test${NC}"
fi
echo ""

# Step 7: Final instructions
echo "================================================"
echo -e "${GREEN}✅ MCP Monitoring Setup Complete!${NC}"
echo "================================================"
echo ""
echo "📊 To use the monitoring system:"
echo ""
echo "1. Source the aliases (add to your shell profile):"
echo "   source ~/.claude/mcp_monitoring/aliases.sh"
echo ""
echo "2. View analytics dashboard:"
echo "   mcp-report         # Default 7-day report"
echo "   mcp-report-week    # 7-day report"
echo "   mcp-report-month   # 30-day report"
echo ""
echo "3. Monitor live activity:"
echo "   mcp-logs           # Watch CSV logs"
echo "   mcp-errors         # Watch error logs"
echo "   mcp-session        # View active session"
echo ""
echo "4. Export metrics:"
echo "   mcp-export         # Export to JSON"
echo ""
echo "5. The hooks will automatically track:"
echo "   • All MCP Python Intelligence tool calls"
echo "   • Grep/find/rg usage in Bash commands"
echo "   • Direct Grep tool usage"
echo "   • Session start/end events"
echo ""
echo "🔄 Hooks are now active and will track all future Claude Code sessions!"
echo ""
echo "💡 Tip: Add this to your .bashrc/.zshrc to load aliases automatically:"
echo "   [[ -f ~/.claude/mcp_monitoring/aliases.sh ]] && source ~/.claude/mcp_monitoring/aliases.sh"
