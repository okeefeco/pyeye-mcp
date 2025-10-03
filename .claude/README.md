# ⚠️ This Directory is for Claude Code, Not Humans

## Humans: You're in the Wrong Place

This directory contains behavioral instructions for Claude Code (AI assistant). These files control how Claude behaves when working on this project.

### Looking for Documentation?

- **Project Overview**: See [`/README.md`](../README.md)
- **Contributing Guide**: See [`/CONTRIBUTING.md`](../CONTRIBUTING.md)
- **Documentation**: See [`/docs`](../docs/)
- **API Reference**: See [`/docs/api`](../docs/api/)

### For Maintainers Only

If you need to modify Claude's behavior:

#### Directory Structure

```text
.claude/
├── instructions/     # Modular behavior rules
│   ├── 00-*.md      # Core understanding
│   ├── 01-*.md      # Fundamental rules
│   ├── 02-*.md      # Startup/context
│   └── ...          # Other behaviors
├── agents/          # Agent definitions
├── feedback/        # Learning/logs
└── settings.json    # Configuration
```

#### Key Files

- `instructions/00-documentation-system.md` - Teaches Claude about documentation
- `instructions/01-core-rules.md` - Critical behavior rules
- `instructions/04-agent-triggers.md` - When to use specific agents

#### Making Changes

1. Changes here immediately affect Claude's behavior
2. Use IMPERATIVE language (MUST, NEVER, ALWAYS)
3. Keep instructions concise and enforceable
4. Don't put human explanations here - use `/docs` instead

#### Understanding the System

The instruction files use a numbered prefix system:

- `00-*` Foundational understanding
- `01-*` Core rules and enforcement
- `02-*` Startup and context detection
- `03-*` Required practices
- `04-*` Behavioral triggers
- `05-07-*` Workflows
- `08-*` Project-specific
- `09-10-*` Tools and utilities

### Warning

Modifying these files changes how Claude behaves across ALL sessions on this project. Be careful and test changes thoroughly.
