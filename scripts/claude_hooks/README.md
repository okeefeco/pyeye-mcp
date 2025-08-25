# MCP Monitoring for Claude Code

Automatic tracking system for monitoring MCP Python Intelligence tool usage vs traditional grep/find patterns using Claude Code's hook system.

## 🚀 Quick Start

```bash
# Run the setup script
bash scripts/claude_hooks/setup_mcp_monitoring.sh

# Load aliases
source ~/.claude/mcp_monitoring/aliases.sh

# View analytics
mcp-report
```

## 📊 What Gets Tracked

The monitoring system automatically tracks:

- **MCP Tool Calls**: Every `mcp__python-intelligence__*` tool invocation
- **Grep Usage**: Detection of grep/rg/find in Bash commands
- **Direct Grep Tool**: Usage of Claude's Grep tool
- **Sessions**: Start/end of Claude Code sessions
- **Success Metrics**: Tool completion and response sizes

## 🎯 Analytics Dashboard

View comprehensive analytics with the `mcp-report` command:

```bash
# 7-day report (default)
mcp-report

# 30-day report
mcp-report-month

# Custom period
python3 scripts/claude_hooks/mcp_analytics.py --days 14

# Export to JSON
mcp-export
```

### Sample Report

```text
============================================================
MCP MONITORING ANALYTICS REPORT
Period: Last 7 days
============================================================

📊 ADOPTION METRICS
----------------------------------------
MCP Tool Calls: 156
Grep/Find Usage: 23
Total Searches: 179
🎯 MCP Adoption Rate: 87.2%

📅 SESSION STATISTICS
----------------------------------------
Total Sessions: 12
Complete Sessions: 10
Active Sessions: 2

🔧 TOP MCP TOOLS USED
----------------------------------------
  find_symbol: 45 calls
  find_references: 32 calls
  get_type_info: 28 calls
  list_modules: 18 calls
  analyze_dependencies: 15 calls

💡 RECOMMENDATIONS
----------------------------------------
🎉 Excellent MCP adoption rate!
  • Continue monitoring for edge cases
  • Share learnings with team
```

## 🔧 How It Works

### Hook System

Claude Code's hook system intercepts tool calls:

1. **PreToolUse Hook**: Captures tool invocations before execution
2. **PostToolUse Hook**: Records successful completions
3. **SessionStart/End Hooks**: Track session boundaries

### Data Files

Monitoring data is stored in `~/.claude/mcp_monitoring/`:

- `mcp_calls.jsonl` - Detailed MCP tool invocations
- `grep_usage.jsonl` - Grep/find command usage
- `mcp_success.jsonl` - Successful tool completions
- `sessions.jsonl` - Session start/end events
- `*.csv` - Simplified CSV versions for quick analysis

## 📈 Integration with Dogfooding Metrics

This system complements the existing dogfooding metrics:

```python
# Sync MCP monitoring data with dogfooding session
python scripts/dogfooding_metrics.py sync

# Combined report
python scripts/dogfooding_metrics.py report --include-hooks
```

## 🛠️ Manual Installation

If you prefer manual setup:

1. **Merge hooks into Claude settings**:

   ```bash
   # Backup existing settings
   cp ~/.config/claude/settings.json ~/.config/claude/settings.json.backup

   # Add hooks to settings.json (requires manual JSON merge)
   # The hooks go inside ~/.config/claude/settings.json, not a separate file
   ```

2. **Update paths in settings.json**:
   - Replace `~/GitHub/python-code-intelligence-mcp` with your repo path
   - Ensure hooks are at the top level of the JSON alongside other settings

3. **Make scripts executable**:

   ```bash
   chmod +x scripts/claude_hooks/*.py
   ```

4. **Create monitoring directory**:

   ```bash
   mkdir -p ~/.claude/mcp_monitoring
   ```

## 📋 Available Commands

After sourcing aliases:

- `mcp-report` - 7-day analytics report
- `mcp-report-week` - Weekly report
- `mcp-report-month` - Monthly report
- `mcp-export` - Export metrics to JSON
- `mcp-logs` - Watch live CSV logs
- `mcp-errors` - Watch error logs
- `mcp-session` - View active session info

## 🔍 Debugging

Check if hooks are working:

```bash
# View recent MCP calls
tail ~/.claude/mcp_monitoring/mcp_calls.jsonl

# Check for errors
cat ~/.claude/mcp_monitoring/hook_errors.log

# Verify hooks are installed
cat ~/.claude/hooks.json
```

## 📊 Metrics Goals

We're tracking progress toward:

- **Week 1**: Establish baseline, >30% MCP usage ✅
- **Week 2**: >50% MCP usage ✅
- **Week 3**: >70% MCP usage ✅
- **Week 4**: >80% MCP usage 🎯

## 🤝 Contributing

To improve the monitoring system:

1. Edit scripts in `scripts/claude_hooks/`
2. Test locally with setup script
3. Submit PR with usage examples

## 📝 Notes

- Hooks run with your user permissions
- Data is stored locally in `~/.claude/`
- No sensitive information is logged
- Hooks are per-user, not per-project
