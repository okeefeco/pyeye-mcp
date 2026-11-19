# Debugging MCP Connection Drops

This guide explains how to use the connection diagnostics features to identify and debug MCP stdio connection drops between PyEye and Claude Code.

## The Problem

Sometimes the MCP server process stays running, but the Claude Code session dies with no indication of why the connection was dropped. This makes it difficult to debug and fix connection issues.

## Solution: Connection Diagnostics

PyEye includes comprehensive connection diagnostics that track:

1. **Connection lifecycle events** - startup, shutdown, activity, errors
2. **Signal handling** - SIGTERM, SIGPIPE, SIGHUP to detect disconnects
3. **Error patterns** - consecutive errors, rapid error rates
4. **Heartbeat monitoring** - periodic logs to identify silent periods
5. **Activity tracking** - each analysis tool call (core and plugin tools) is logged with a timestamp

## Enabling Diagnostics

### 1. Enable File Logging

Set the `PYEYE_LOG_FILE` environment variable to capture all logs to a
persistent file. The MCP client starts the server, so set it on the server
entry (an `export` in your shell reaches the server only if the client was
started from that shell). For Claude Code, remove the server and add it again
with the variables, using the command you registered it with (here
`uvx pyeye-mcp`):

```bash
claude mcp remove pyeye
claude mcp add pyeye -s user -e PYEYE_LOG_FILE=$HOME/.pyeye/connection.log -e PYEYE_LOG_LEVEL=INFO -- uvx pyeye-mcp
```

For Claude Desktop, add an `env` block to pyeye's entry in its config file (see
the README's [Other MCP clients](../README.md#other-mcp-clients)):

```json
{
  "mcpServers": {
    "pyeye": {
      "command": "uvx",
      "args": ["pyeye-mcp"],
      "env": {
        "PYEYE_LOG_FILE": "/Users/yourname/.pyeye/connection.log",
        "PYEYE_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

### 2. Enable Performance Metrics (Optional)

To access the `get_connection_diagnostics` tool, enable performance metrics
on the server entry. For Claude Code, add `-e PYEYE_ENABLE_PERFORMANCE_METRICS=true`
to the `claude mcp add` command above. In the Claude Desktop config:

```json
{
  "mcpServers": {
    "pyeye": {
      "command": "uvx",
      "args": ["pyeye-mcp"],
      "env": {
        "PYEYE_LOG_FILE": "/Users/yourname/.pyeye/connection.log",
        "PYEYE_LOG_LEVEL": "INFO",
        "PYEYE_ENABLE_PERFORMANCE_METRICS": "true"
      }
    }
  }
}
```

## What Gets Logged

### Connection Lifecycle

```log
2026-04-01 10:15:23 [PID 12345] pyeye.mcp.connection_diagnostics INFO: ============================================================
2026-04-01 10:15:23 [PID 12345] pyeye.mcp.connection_diagnostics INFO: MCP CONNECTION STARTED
2026-04-01 10:15:23 [PID 12345] pyeye.mcp.connection_diagnostics INFO: Start time: 2026-04-01T10:15:23.456789
2026-04-01 10:15:23 [PID 12345] pyeye.mcp.connection_diagnostics INFO: Python: 3.12.0
2026-04-01 10:15:23 [PID 12345] pyeye.mcp.connection_diagnostics INFO: PID: 12345
2026-04-01 10:15:23 [PID 12345] pyeye.mcp.connection_diagnostics INFO: ============================================================
```

### Tool Call Activity

```log
2026-04-01 10:15:30 [PID 12345] pyeye.mcp.connection_diagnostics INFO: [CONNECTION] tool_call: resolve
2026-04-01 10:15:32 [PID 12345] pyeye.mcp.connection_diagnostics INFO: [CONNECTION] tool_call: inspect
```

### Heartbeat

```log
2026-04-01 10:16:00 [PID 12345] pyeye.mcp.connection_diagnostics INFO: [CONNECTION] heartbeat: idle_for=5.2s
```

### Error Tracking

```log
2026-04-01 10:16:15 [PID 12345] pyeye.mcp.error_tracker ERROR: [ERROR_TRACKER] Tool 'resolve' raised FileNotFoundError: ...
2026-04-01 10:16:16 [PID 12345] pyeye.mcp.error_tracker WARNING: [ERROR_TRACKER] 3 consecutive errors detected - connection may be unstable
```

### Signal Detection

```log
2026-04-01 10:20:00 [PID 12345] pyeye.mcp.connection_diagnostics WARNING: Received SIGTERM - client likely disconnected
```

```log
2026-04-01 10:20:00 [PID 12345] pyeye.mcp.connection_diagnostics ERROR: Received SIGPIPE - stdio pipe broken, client disconnected unexpectedly
2026-04-01 10:20:00 [PID 12345] pyeye.mcp.connection_diagnostics ERROR: Connection summary at disconnect: {'uptime_seconds': 276.5, ...}
```

### Shutdown Diagnostics

```log
2026-04-01 10:20:00 [PID 12345] pyeye.mcp.__main__ INFO: ============================================================
2026-04-01 10:20:00 [PID 12345] pyeye.mcp.__main__ INFO: SHUTDOWN DIAGNOSTICS
2026-04-01 10:20:00 [PID 12345] pyeye.mcp.__main__ INFO: ============================================================
2026-04-01 10:20:00 [PID 12345] pyeye.mcp.__main__ INFO: Connection uptime: 276.5 seconds
2026-04-01 10:20:00 [PID 12345] pyeye.mcp.__main__ INFO: Total connection events: 42
2026-04-01 10:20:00 [PID 12345] pyeye.mcp.__main__ INFO: Final idle time: 5.2 seconds
2026-04-01 10:20:00 [PID 12345] pyeye.mcp.__main__ INFO: Total errors: 3
2026-04-01 10:20:00 [PID 12345] pyeye.mcp.__main__ INFO: Error types: {'FileNotFoundError': 2, 'ValueError': 1}
```

## Using the Diagnostic Tool (Live Query)

If `PYEYE_ENABLE_PERFORMANCE_METRICS=true`, you can query diagnostics in real-time:

```python
# From Claude Code or any MCP client
result = await client.call_tool("get_connection_diagnostics")
```

Returns:

```json
{
  "connection": {
    "start_time": "2026-04-01T10:15:23.456789",
    "uptime_seconds": 276.5,
    "idle_seconds": 5.2,
    "stdin_alive": true,
    "stdout_alive": true,
    "total_events": 42,
    "recent_events": [...]
  },
  "errors": {
    "total_errors": 3,
    "error_counts_by_type": {"FileNotFoundError": 2, "ValueError": 1},
    "consecutive_errors": 0,
    "last_error_time": "2026-04-01T10:16:16.789",
    "recent_errors": [...]
  },
  "pattern_warning": null,
  "status": "healthy"
}
```

## Analyzing Logs

### Finding Connection Drops

```bash
# Search for disconnect signals
grep -i "sigpipe\|sigterm" ~/.pyeye/connection.log

# Find the last connection session
grep "MCP CONNECTION STARTED" ~/.pyeye/connection.log | tail -1
```

### Identifying Error Patterns

```bash
# Find error spikes
grep "ERROR_TRACKER" ~/.pyeye/connection.log

# Find consecutive error warnings
grep "consecutive errors" ~/.pyeye/connection.log
```

### Tracking Idle Periods

```bash
# Find long idle periods (>5 minutes)
grep "heartbeat" ~/.pyeye/connection.log | awk -F'idle_for=' '{ if ($2+0 > 300) print }'
```

### Filtering by Session

Each log line includes PID, so you can filter by specific session:

```bash
# Find all logs for PID 12345
grep "\[PID 12345\]" ~/.pyeye/connection.log
```

## Common Disconnect Patterns

### SIGPIPE - Broken Pipe

**Symptom**: `Received SIGPIPE - stdio pipe broken`

**Meaning**: The client (Claude Code) closed the connection unexpectedly without proper shutdown.

**Common Causes**:

- Claude Code crashed or was force-quit
- Network interruption (if using remote stdio)
- Client-side timeout

### SIGTERM - Graceful Shutdown Request

**Symptom**: `Received SIGTERM - client likely disconnected`

**Meaning**: The client requested a graceful shutdown.

**Common Causes**:

- User closed Claude Code normally
- System shutdown
- Process manager (systemd, launchd) stopping the service

### High Consecutive Errors

**Symptom**: `X consecutive errors detected - connection may be unstable`

**Meaning**: Multiple tool calls failing in a row.

**Common Causes**:

- Invalid project configuration
- File system issues
- Python environment problems
- Jedi analysis failures

### Silent Disconnects

**Symptom**: Heartbeat logs show increasing idle time, then nothing

**Meaning**: Connection stopped without any signal.

**Common Causes**:

- Parent process died (Claude Code crashed)
- Lost stdio pipes
- System-level process termination

## Troubleshooting Steps

1. **Check the log file** - Look for the last session's logs
2. **Identify the disconnect type** - SIGPIPE, SIGTERM, or silent
3. **Review recent errors** - Were there errors before disconnect?
4. **Check idle time** - How long was the connection idle?
5. **Inspect tool calls** - What was the last successful operation?

## Advanced: Adjusting Heartbeat Interval

To change the heartbeat interval, edit the
`start_heartbeat_monitor(interval_seconds=30)` call in `main()` in
`src/pyeye/mcp/__main__.py`:

```python
# Start heartbeat monitor (logs every 60 seconds instead of 30)
start_heartbeat_monitor(interval_seconds=60)
```

## Future Enhancements

Potential improvements to connection diagnostics:

- Stdio stream health checks (detect closed pipes before write)
- Memory usage tracking (detect memory leaks)
- Request/response latency tracking (detect performance degradation)
- Client capability negotiation logging
- Automatic reconnection attempts
