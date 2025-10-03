# Dogfooding Metrics Integration

This document describes the integration between MCP performance metrics and dogfooding metrics tracking, implemented in issue #170.

## Problem Statement

The original dogfooding metrics system was reporting 0% MCP adoption despite heavy MCP tool usage during development. This was because:

1. MCP tool calls from Claude were not being captured
2. No integration existed between the MCP server's performance metrics and the dogfooding tracker
3. Grep usage detection was incomplete

## Solution Architecture

### Components

1. **`pycodemcp/dogfooding_integration.py`** - Bridge between MCP metrics and dogfooding tracker
2. **Enhanced `scripts/dogfooding_metrics.py`** - Updated to use MCP metrics integration
3. **`scripts/grep_tracker.sh`** - Shell wrapper for detecting grep usage
4. **`scripts/setup_grep_tracking.sh`** - Automated setup for grep detection

### Data Flow

```text
Claude MCP Calls → MCP Server → MetricsCollector → DogfoodingIntegration → Session Storage
                                                                        ↓
Shell Commands → grep_tracker.sh → dogfooding_metrics.py → Session Storage
```

## Key Features

### Automatic MCP Tool Tracking

- All MCP tools are decorated with `@metrics.measure()` in `server.py`
- `DogfoodingIntegration.export_mcp_metrics_for_session()` extracts tool usage data
- Real-time sync via `python scripts/dogfooding_metrics.py sync`

### Grep Usage Detection

- Wrapper scripts for `grep`, `egrep`, `fgrep`, `rg`
- Intelligent filtering - only tracks code search patterns
- Automatic setup via `scripts/setup_grep_tracking.sh`

### Session Integration

- Baseline metrics captured at session start
- Delta calculation at session end
- Real-time sync updates during active sessions

## API Reference

### DogfoodingIntegration Class

```python
from pyeye.dogfooding_integration import get_integration

integration = get_integration()

# Export current MCP metrics
metrics = integration.export_mcp_metrics_for_session()

# Log individual tool calls
integration.log_mcp_call("find_symbol", {"name": "TestClass"})

# Update active session with latest metrics
success = integration.update_session_with_mcp_stats()

# Calculate MCP adoption rate
rates = integration.get_mcp_adoption_rate()
```

### CLI Commands

```bash
# Start session with MCP metrics baseline
python scripts/dogfooding_metrics.py start --issue 170

# Sync current MCP metrics to active session
python scripts/dogfooding_metrics.py sync

# Manual logging
python scripts/dogfooding_metrics.py grep
python scripts/dogfooding_metrics.py saved 10 "Found refs instantly"
python scripts/dogfooding_metrics.py bug "Prevented circular import"

# End session with final metrics delta
python scripts/dogfooding_metrics.py end

# Generate report with real MCP adoption rates
python scripts/dogfooding_metrics.py report --days 7
```

## Setup Instructions

### Automatic Setup (Recommended)

```bash
# Full setup including MCP integration and grep tracking
bash scripts/setup_dogfooding.sh
```

### Manual Setup

```bash
# Setup grep tracking only
bash scripts/setup_grep_tracking.sh

# Test MCP integration
python scripts/dogfooding_metrics.py start --issue test
python scripts/dogfooding_metrics.py sync
python scripts/dogfooding_metrics.py end
```

## Metrics Data Structure

### Session with MCP Integration

```json
{
  "id": "2025-08-24T11:14:12.764119",
  "issue": 170,
  "start_time": "2025-08-24T11:14:12.764134",
  "baseline_metrics": {
    "total_mcp_calls": 0,
    "tool_calls": [],
    "cache_stats": {"hits": 0, "misses": 0},
    "memory_stats": {"rss_mb": 64.0}
  },
  "final_metrics": {
    "total_mcp_calls": 15,
    "tool_calls": [
      {"tool": "find_symbol", "count": 8, "avg_ms": 45.2},
      {"tool": "find_references", "count": 5, "avg_ms": 120.8},
      {"tool": "get_type_info", "count": 2, "avg_ms": 35.1}
    ]
  },
  "grep_count": 2,
  "stats": {
    "mcp_queries_count": 15,
    "grep_count": 2,
    "mcp_ratio": 0.88,  // 15/(15+2) = 88% MCP adoption
    "duration_minutes": 12.5
  }
}
```

### MCP Tool Usage Log

```jsonl
{"timestamp": "2025-08-24T11:15:30", "tool": "find_symbol", "params": {"name": "MetricsCollector"}}
{"timestamp": "2025-08-24T11:16:45", "tool": "find_references", "params": {"file": "/path/to/file.py", "line": 107}}
```

## Testing

The integration includes comprehensive tests in `tests/test_dogfooding_integration.py`:

```bash
# Run integration tests
uv run pytest tests/test_dogfooding_integration.py -v

# Test specific functionality
uv run pytest tests/test_dogfooding_integration.py::test_export_mcp_metrics_for_session -v
```

## Troubleshooting

### "0 MCP calls synced" Issue

This typically means:

1. No active dogfooding session - run `python scripts/dogfooding_metrics.py start --issue <num>`
2. MCP server instance isolation - the metrics are in a different server instance
3. Import path issues - ensure `src/` is in PYTHONPATH

### Grep Tracking Not Working

Check:

1. Shell aliases are active: `source ~/.bashrc`
2. `~/.local/bin` is in PATH: `echo $PATH | grep local/bin`
3. Wrapper scripts exist: `ls -la ~/.local/bin/grep`

### Performance Impact

The integration is designed to be lightweight:

- Metrics export: < 1ms overhead
- Log file writes: Async, non-blocking
- Session updates: Only on explicit `sync` calls

## Future Improvements

1. **Real-time Integration**: Hook directly into MCP server request handlers
2. **Claude Hook Integration**: Use Claude Code hooks for automatic syncing
3. **Web Dashboard**: Real-time metrics visualization
4. **Team Analytics**: Aggregate metrics across multiple developers
5. **Pattern Recognition**: AI-driven insights on MCP usage patterns

## Related Issues

- #170: Fix MCP usage tracking in dogfooding metrics
- #135: Original dogfooding metrics implementation
- Future: Real-time MCP metrics dashboard
