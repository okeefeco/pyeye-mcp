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

### Updating an existing setup

The setup script merges the hooks from `hooks.json` into your
`~/.claude/settings.json`. It keeps your other settings and your own hooks,
replaces only pyeye's (any command under `scripts/claude_hooks/`), and backs up
the file first, so re-running it is safe (#981; before that, a run replaced
your whole `hooks` section, or the whole file when `jq` wasn't installed). A
change to the hooks reaches you only when you re-run it. If you set up monitoring before the plugin's tool names were matched
(#965), or before the Grep tool was counted (#970, which points the `Grep` hook
at `track_grep_tool.py`), re-run `bash scripts/claude_hooks/setup_mcp_monitoring.sh`
once. The tracking scripts themselves run from this
repository, so changes to them need nothing.

## 📊 What Gets Tracked

The monitoring system automatically tracks:

- **MCP Tool Calls**: Every pyeye tool invocation, under either name Claude Code gives it: `mcp__pyeye__*` (added with `claude mcp add`) or `mcp__plugin_pyeye_pyeye__*` (the Claude Code plugin). Both are recorded under the tool's own name, such as `resolve`.
- **Grep Usage**: Detection of grep/rg/find in Bash commands
- **Direct Grep Tool**: Usage of Claude's Grep tool (`track_grep_tool.py`), counted with grep usage in the report
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

### What the Report Shows

`mcp_analytics.py` prints these sections, in order, for the period you ask for:

- **Adoption metrics**: MCP tool calls, grep/find usage, and the MCP adoption
  rate (MCP calls as a share of all searches).
- **Session statistics**: total, complete and active sessions.
- **Top MCP tools used** and a **grep tool breakdown**, when there is data.
- **Recommendations**, chosen from the adoption rate.

Run `mcp-report` to see it for your own sessions.

## 🔧 How It Works

### Hook System

Claude Code's hook system intercepts tool calls:

1. **PreToolUse Hook**: Captures tool invocations before execution
2. **PostToolUse Hook**: Records successful completions
3. **SessionStart/End Hooks**: Track session boundaries

### Data Files

Monitoring data is stored in `~/.claude/mcp_monitoring/`:

- `mcp_calls.jsonl` - Detailed MCP tool invocations
- `grep_usage.jsonl` - Grep/find command usage, and Grep tool calls (tool `grep_tool`)
- `mcp_success.jsonl` - Successful tool completions
- `sessions.jsonl` - Session start/end events
- `*.csv` - Simplified CSV versions for quick analysis

## 📈 Integration with Dogfooding Metrics

This system is where MCP calls are counted. The dogfooding CLI (`scripts/dogfooding_metrics.py`) tracks sessions, grep use and logged notes, but it runs outside the MCP server's process, so it can't see MCP calls (#879). Use `mcp-report` and `mcp-logs` for those.

## 🛠️ Manual Installation

If you prefer manual setup:

1. **Merge hooks into Claude settings**:

   ```bash
   # Backup existing settings
   cp ~/.claude/settings.json ~/.claude/settings.json.backup

   # Add hooks to settings.json (requires manual JSON merge)
   # The hooks go inside ~/.claude/settings.json, not a separate file
   ```

2. **Update paths in settings.json**:
   - Replace `~/GitHub/pyeye-mcp` with your repo path
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

# Verify hooks are installed (setup merges them into your settings)
python3 -c "import json, pathlib; print(json.dumps(json.load(open(pathlib.Path.home() / '.claude/settings.json')).get('hooks', {}), indent=2))"
```

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
