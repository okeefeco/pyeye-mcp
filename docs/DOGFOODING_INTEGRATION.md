# Dogfooding Metrics Integration

How the pieces that measure our own use of pyeye fit together: the dogfooding
session CLI, grep tracking, and the Claude Code hooks that count MCP calls.

## Where each number comes from

| What | Recorded by | Where it lands |
|------|-------------|----------------|
| MCP tool calls made by Claude | The Claude Code hooks in [`scripts/claude_hooks/`](../scripts/claude_hooks/README.md) | `~/.claude/mcp_monitoring/` |
| Manual searches (`grep`, `rg`, …) | `scripts/grep_tracker.sh`, installed by `scripts/setup_grep_tracking.sh` | the active dogfooding session |
| MCP queries you log by hand, time saved, bugs prevented | `scripts/dogfooding_metrics.py` (`mcp`, `saved`, `bug`) | the active dogfooding session |

The dogfooding CLI runs outside the MCP server's process, so it can't see the
server's own call counts. It counts the MCP queries logged into the session
through its `mcp` command (which `scripts/mcp_wrapper.sh` calls). For the calls
Claude actually makes, use the hooks: `mcp-report` for usage reports and
`mcp-logs` to watch calls live (aliases installed by
`scripts/claude_hooks/setup_mcp_monitoring.sh`). Earlier versions read an
in-process collector that is always empty outside the server, so they reported
zero MCP calls (#879, #915).

```text
Claude MCP calls → Claude Code hooks → ~/.claude/mcp_monitoring/   (mcp-report, mcp-logs)

Shell searches  → grep_tracker.sh ─┐
mcp / saved / bug commands ────────┴→ dogfooding_metrics.py → ~/.pyeye/metrics/ session
```

## Grep usage detection

- Wrapper scripts for `grep`, `egrep`, `fgrep` and `rg`.
- Only searches that look like code searches are counted.
- Set up with `scripts/setup_grep_tracking.sh`.

## CLI commands

```bash
# Start a session (also started automatically on checkout of an issue branch)
uv run --frozen python scripts/dogfooding_metrics.py start --issue 170

# Manual logging
uv run --frozen python scripts/dogfooding_metrics.py grep
uv run --frozen python scripts/dogfooding_metrics.py mcp resolve
uv run --frozen python scripts/dogfooding_metrics.py saved 10 "Found refs instantly"
uv run --frozen python scripts/dogfooding_metrics.py bug "Prevented circular import"

# End the session and show its stats
uv run --frozen python scripts/dogfooding_metrics.py end

# Report on recent sessions
uv run --frozen python scripts/dogfooding_metrics.py report --days 7
```

## Setup

```bash
# Git hooks, shell aliases, grep tracking and the metrics directory
bash scripts/setup_dogfooding.sh

# The Claude Code hooks that count MCP calls (mcp-report, mcp-logs)
bash scripts/claude_hooks/setup_mcp_monitoring.sh

# Or grep tracking alone
bash scripts/setup_grep_tracking.sh
```

## Session data

An ended session, as appended to `~/.pyeye/metrics/history.jsonl`:

```json
{
  "id": "2025-08-24T11:14:12.764119",
  "issue": 170,
  "start_time": "2025-08-24T11:14:12.764134",
  "end_time": "2025-08-24T11:26:42.901233",
  "grep_count": 2,
  "mcp_queries": [
    {"tool": "resolve", "duration_ms": 100, "success": true, "timestamp": "2025-08-24T11:15:30"}
  ],
  "time_saved_estimates": [],
  "bugs_prevented": [],
  "stats": {
    "duration_minutes": 12.5,
    "mcp_queries_count": 1,
    "grep_count": 2,
    "mcp_ratio": 0.33,
    "bugs_prevented": 0,
    "time_saved_minutes": 0
  }
}
```

`mcp_ratio` is the logged MCP query count over all searches: 1 / (1 + 2).
`duration_ms` is a placeholder: the `mcp` command logs 100 for every query, so
it says nothing about how long the query took.
Sessions saved by older versions also carry `baseline_metrics` and
`final_metrics`; nothing reads them.

## Testing

```bash
uv run pytest tests/test_dogfooding_metrics.py tests/test_dogfooding_workflow.py -v
```

## Troubleshooting

### Grep tracking not working

Check:

1. Shell aliases are active: `source ~/.bashrc`
2. `~/.local/bin` is in PATH: `echo $PATH | grep local/bin`
3. Wrapper scripts exist: `ls -la ~/.local/bin/grep`

## Related issues

- #170: Fix MCP usage tracking in dogfooding metrics
- #135: Original dogfooding metrics implementation
- #879, #915: The CLI no longer pretends to read the server's MCP counts
