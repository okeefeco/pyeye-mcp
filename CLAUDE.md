# Python Code Intelligence MCP Server - Claude Instructions

This file loads modular Claude behavior instructions. The actual instructions are in `.claude/instructions/`.

## 🎯 CRITICAL: First, Understand the Documentation System

@.claude/instructions/00-documentation-system.md

## Core Behavior and Rules

@.claude/instructions/01-core-rules.md
@.claude/instructions/02-session-startup.md

## Development Workflows

@.claude/instructions/05-workflow-issues.md
@.claude/instructions/06-workflow-commits.md
@.claude/instructions/07-validation.md

## Required Development Practices

@.claude/instructions/03-mcp-dogfooding.md
@.claude/instructions/04-agent-triggers.md

## Tools and Utilities

@.claude/instructions/09-task-management.md
@.claude/instructions/10-cross-platform.md

## Project-Specific Configuration

@.claude/instructions/08-project-specific.md

## Required Context Files

These files provide essential project context and are automatically loaded:

@CONTRIBUTING.md - GitHub issue workflow, merge strategy, validation rules, development setup
@docs/LABELS.md - GitHub issue labeling system and priorities

**CRITICAL**: The workflows in CONTRIBUTING.md are MANDATORY. Always follow the GitHub issue-based workflow and NEVER use squash merges.

## Detailed Worktree-Aware Workflow

@.claude/startup-context.md

## Optional User-Specific Configuration

For personal development settings (worktrees, local paths, etc.):

@~/.claude/projects/okeefeco/python-code-intelligence-mcp.md

This file is optional and ignored if it doesn't exist. It won't be committed to the repository.

## Dogfooding Metrics Tracking

To measure our MCP adoption:

```bash
# View real-time analytics
mcp-report         # 7-day report
mcp-report-month   # 30-day report
mcp-logs          # Watch live activity
mcp-session       # View active session
mcp-errors        # Check for hook errors
```

Metrics tracking is automatic via Claude Code hooks. See `scripts/claude_hooks/README.md` for details.

---

**For Humans**: This directory contains Claude's behavioral instructions. See `.claude/README.md` for details.

**For Claude**: You MUST read and follow ALL imported instruction files above. They define your required behavior.
