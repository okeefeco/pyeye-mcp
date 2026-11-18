# Unified Metrics (deprecated)

The unified metrics store is gone. The MCP server no longer records sessions or
writes usage metrics to `~/.pyeye/metrics/` (#943). Nothing that shipped ever read
that store, and recording it cost every MCP call a locked rewrite of a file.

What still exists, for 2.x only, so nothing that used it breaks:

- `pyeye.unified_metrics.get_unified_collector()` emits a `DeprecationWarning` and
  returns a collector that accepts the old calls and records nothing.
- `scripts/unified_metrics.py` prints a deprecation notice and exits.
- `PYEYE_ISSUE` and `PYEYE_PARENT_SESSION` are deprecated: accepted and ignored.

These go in a future major release (#749).

## Files left on your machine

Files the server wrote before can be deleted: `active_sessions.json`,
`completed_sessions.jsonl`, `aggregated_stats.json` and their `.lock` files,
under `~/.pyeye/metrics/`. Other files in that directory (`history.jsonl`,
`current_session.json`) belong to the dogfooding scripts; see
[DOGFOODING_INTEGRATION.md](DOGFOODING_INTEGRATION.md).

## Where MCP usage is measured now

The Claude Code hooks in [`scripts/claude_hooks/`](../scripts/claude_hooks/README.md)
record MCP calls: `mcp-report` for usage reports, `mcp-logs` to watch calls live.
The server's in-process performance metrics are available through the
`get_performance_metrics` admin tool.
