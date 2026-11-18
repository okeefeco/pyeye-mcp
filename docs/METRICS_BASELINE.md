# Dogfooding Metrics Baseline

## Date: 2025-08-22

> **Historical record.** This baseline was taken against the v1 tool surface, and
> the tool names below are the ones in use at the time. Most of them were removed
> in 2.0; the CHANGELOG's migration map lists their replacements. It is kept as a
> record of where adoption started. Figures with no reproducible record, and the
> targets and projections, were removed (#830).

### Current State (Before Dogfooding Initiative)

Based on analysis of recent development patterns:

#### Common Anti-patterns Observed

1. Using `grep -r "class_name"` instead of `find_symbol`
2. Reading entire files to find functions
3. Not checking references before renaming
4. Manual dependency tracing
5. No usage of subclass finding

### Metrics to Track

1. **MCP Usage Rate**: (MCP queries) / (MCP queries + grep usage)
2. **Time Saved**: Estimated minutes saved per session
3. **Bugs Prevented**: Count of issues caught by MCP
4. **Feature Gaps**: List of missing capabilities discovered

### Baseline Session (Issue #135)

- Session start: 2025-08-22 20:52:15

### Historical Context

From previous PRs without dogfooding:

- PR #77: a cache bug that broke existing tests
- PR #121: Flask plugin test coverage, where cross-platform path issues surfaced (see issue #110)
- PR #122: Test coverage gaps

## Planned Next Steps (2025-08-22)

1. Continue tracking all development sessions
2. Weekly review of metrics every Friday
3. Adjust workflows based on discoveries
4. Share findings with team

## How to Contribute

When you discover a pattern or time-saver:

1. Log it: `python scripts/dogfooding_metrics.py saved <minutes> "<reason>"`
2. Describe it in the issue or PR where you found it
