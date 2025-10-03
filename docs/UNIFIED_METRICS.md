# Unified Metrics System

The Unified Metrics System provides comprehensive tracking and reporting of MCP operations across all Claude sessions, including main sessions, subagents, and parallel task execution.

## Overview

### Problem Solved

Previously, each Claude session (including subagents) had isolated MCP server instances, making it impossible to:

- Track unified metrics across all development activity
- See MCP usage from Task subagents
- Monitor adoption rates across the entire development workflow
- Understand the relationship between main sessions and their subagents

### Solution

The Unified Metrics System provides:

- **Persistent Storage**: Metrics survive session restarts and are aggregated globally
- **Session Hierarchy**: Tracks parent-child relationships between main sessions and subagents
- **Cross-Session Reporting**: Comprehensive reports across all MCP activity
- **Real-time Monitoring**: Live view of active sessions and their operations
- **Thread-Safe Operations**: Concurrent access from multiple MCP server instances

## Architecture

### Components

```text
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Main Session  │    │   Task Agent    │    │  Other Session  │
│   MCP Server    │    │   MCP Server    │    │   MCP Server    │
└─────────┬───────┘    └─────────┬───────┘    └─────────┬───────┘
          │                      │                      │
          └──────────────────────┼──────────────────────┘
                                 │
                    ┌────────────▼───────────┐
                    │  Unified Metrics       │
                    │  Persistent Storage    │
                    │  (~/.pycodemcp/       │
                    │   unified_metrics/)    │
                    └────────────┬───────────┘
                                 │
                    ┌────────────▼───────────┐
                    │  Reporting & Analysis  │
                    │  (scripts/unified_     │
                    │   metrics.py)          │
                    └────────────────────────┘
```

### Storage Structure

```text
~/.pycodemcp/unified_metrics/
├── active_sessions.json      # Currently running sessions
├── completed_sessions.jsonl  # Historical session data
└── aggregated_stats.json     # Pre-computed statistics
```

## Usage

### Automatic Integration

The system works automatically when MCP tools are used:

1. **MCP Server Startup**: Automatically creates a session
2. **Tool Calls**: Each MCP operation is tracked with timing
3. **Session End**: Statistics are calculated and stored
4. **Aggregation**: Global statistics are updated

### Session Types

- **`main`**: Primary Claude session
- **`subagent`**: Task/specialized agents spawned from main sessions
- **`auto`**: Auto-created sessions for standalone MCP usage

### Manual Session Management (Optional)

```python
from pyeye.unified_metrics import get_unified_collector

collector = get_unified_collector()

# Start a session
session_id = collector.start_session(
    session_type="main",
    metadata={"issue": 189, "description": "Unified metrics implementation"}
)

# Record operations (happens automatically via hooks)
collector.record_mcp_operation("find_symbol", success=True, duration_ms=45.2)
collector.record_grep_operation()

# End session
final_stats = collector.end_session(session_id)
```

## Command Line Interface

The `scripts/unified_metrics.py` tool provides comprehensive reporting:

### Quick Status

```bash
python scripts/unified_metrics.py status
```

Shows currently active sessions and today's activity.

### Comprehensive Reports

```bash
# Last 7 days (default)
python scripts/unified_metrics.py report

# Last 30 days with verbose details
python scripts/unified_metrics.py report --days 30 --verbose

# Export for external tools
python scripts/unified_metrics.py dashboard --format json
```

### Example Output

```text
============================================================
  📊 METRICS REPORT - Last 7 days
============================================================

📋 Summary:
  Total Sessions: 15
  Active Sessions: 2
  MCP Operations: 247
  Grep Operations: 23
  MCP Adoption Rate: 91.5%

🔧 Most Used MCP Tools:
  1. find_symbol: 89 uses
  2. find_references: 45 uses
  3. get_module_info: 34 uses
  4. analyze_dependencies: 28 uses
  5. find_subclasses: 21 uses

🎭 Session Types:
  main: 8 sessions
  subagent: 6 sessions
  auto: 1 sessions

🔄 Active Sessions:
  main_2025-08-24T16:59:29 (main) - 45.2m - 15 ops
    └── task_coverage_agent (subagent) - 12.1m - 89 ops
```

## Integration with Existing Systems

### Dogfooding Metrics

The unified system complements the existing dogfooding metrics:

- Dogfooding tracks user behavior and manual operations
- Unified metrics capture all MCP server activity
- Both systems can be used together for complete visibility

### Performance Metrics

The unified system works alongside the existing performance metrics:

- Performance metrics track individual operation timing
- Unified metrics track cross-session aggregation
- Both provide different views of the same activity

## Data Models

### SessionMetrics

```python
@dataclass
class SessionMetrics:
    session_id: str
    session_type: str  # "main", "subagent", "task"
    parent_session: str | None
    start_time: str
    end_time: str | None
    mcp_operations: dict[str, int]  # tool_name -> count
    grep_operations: int
    total_operations: int
    errors: int
    cache_hits: int
    cache_misses: int
    memory_peak_mb: float
    metadata: dict[str, Any]
```

### Key Metrics Tracked

- **Operation Counts**: Per-tool usage statistics
- **Timing Data**: Operation duration and frequency
- **Success Rates**: Error tracking per tool
- **Cache Performance**: Hit/miss ratios
- **Session Relationships**: Parent-child hierarchy
- **Activity Patterns**: Hourly/daily usage trends

## Performance Considerations

### File Locking

The system uses `fcntl` file locking to ensure thread-safe access:

- Multiple MCP server instances can write concurrently
- Readers block writers appropriately
- Lock duration is minimized for performance

### Storage Efficiency

- **JSON**: For frequently updated active sessions
- **JSONL**: For append-only historical data
- **Aggregation**: Pre-computed statistics reduce query time
- **Cleanup**: Automatic removal of old data (future enhancement)

### Memory Usage

- Minimal memory footprint per session
- No in-memory caching (uses filesystem as cache)
- Thread-local storage for current session tracking

## Development and Testing

### Test Coverage

The system has comprehensive test coverage:

- **unified_metrics.py**: 99% coverage (181 lines)
- **metrics_hook.py**: 100% coverage (51 lines)
- **CLI tool**: 100% functional coverage

### Testing Approach

- **Thread Safety**: Concurrent file access scenarios
- **Error Handling**: Malformed data, permission errors
- **Integration**: End-to-end workflow validation
- **Performance**: CI-aware timing thresholds

### Running Tests

```bash
# Run unified metrics tests
pytest tests/test_unified_metrics.py tests/test_metrics_hook.py tests/test_unified_metrics_cli.py -v

# With coverage
pytest tests/test_unified_metrics.py tests/test_metrics_hook.py tests/test_unified_metrics_cli.py --cov=src/pyeye/unified_metrics --cov=src/pyeye/metrics_hook
```

## Future Enhancements

### Planned Features

1. **Data Cleanup**: Automatic archival of old session data
2. **Alerts**: Notifications for unusual patterns or performance degradation
3. **Dashboard**: Web-based real-time visualization
4. **Export Formats**: Prometheus metrics, CSV reports
5. **Advanced Analytics**: Trend analysis, performance predictions

### Integration Opportunities

1. **IDE Extensions**: Show metrics in development environment
2. **CI/CD**: Track metrics across development pipeline
3. **Monitoring**: Integration with existing monitoring systems
4. **A/B Testing**: Compare different MCP usage patterns

## Troubleshooting

### Common Issues

#### No sessions showing up

- Verify MCP server is using the enhanced version with unified metrics
- Check file permissions on `~/.pycodemcp/unified_metrics/`

#### Concurrent access errors

- File locking issues in containerized environments
- Consider using different storage backends for high-concurrency scenarios

#### Missing data

- Session ended unexpectedly (process killed)
- File corruption (rare, but check JSON syntax)

### Debug Commands

```bash
# Check storage directory
ls -la ~/.pycodemcp/unified_metrics/

# Validate JSON files
python -m json.tool ~/.pycodemcp/unified_metrics/active_sessions.json

# Check recent activity
tail ~/.pycodemcp/unified_metrics/completed_sessions.jsonl
```

### Log Analysis

The unified metrics system logs to the same location as the MCP server:

- Session creation/destruction events
- File operation errors
- Performance warnings

## Related Documentation

- [DOGFOODING_INTEGRATION.md](DOGFOODING_INTEGRATION.md) - Integration with dogfooding metrics
- [CONTRIBUTING.md](../CONTRIBUTING.md) - Development workflow
- [GitHub Issue #189](https://github.com/okeefeco/pyeye-mcp/issues/189) - Original feature request
