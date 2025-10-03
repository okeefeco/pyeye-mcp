<!--
Audience: Claude Code
Purpose: Teach Claude about documentation types and where to place content
When to update: When documentation structure changes or new patterns emerge
-->

# Documentation System Understanding

## CRITICAL: You (Claude) Must Understand These Documentation Types

### 1. Claude Instructions (Your Instructions)

- **Location**: CLAUDE.md, .claude/instructions/
- **Purpose**: Tell you (Claude) how to behave
- **Audience**: You (Claude Code)
- **Language**: MUST, NEVER, ALWAYS, MANDATORY, CRITICAL
- **When to use**: Behavior rules, patterns, triggers, enforcement
- **Example**: "NEVER use --force without permission"
- **Key characteristic**: Imperative, directive, enforceable

### 2. Human Documentation

- **Location**: README.md, docs/, CONTRIBUTING.md
- **Purpose**: Help humans understand the project
- **Audience**: Human developers
- **Language**: Descriptive, educational, explanatory
- **When to use**: Features, concepts, guides, tutorials
- **Example**: "This project uses semantic versioning"
- **Key characteristic**: Explanatory, informative, educational

### 3. Bridge Documentation

- **Location**: Troubleshooting guides, API docs, command references
- **Purpose**: Humans read to understand, Claude can execute from
- **Audience**: Both humans and Claude
- **Language**: Problem description + solution commands
- **When to use**: Fixes, solutions, examples with commands
- **Example**: "If X error occurs, run: `command`"
- **Key characteristic**: Descriptive problem with executable solution

## Rules for You (Claude) When Creating Documentation

### MANDATORY: Determine Audience First

When someone asks you to document something, ALWAYS ask yourself:

1. **Is this teaching Claude behavior?**
   - Keywords: "always", "never", "must", "enforce", "trigger"
   - Action: Create/update in `.claude/instructions/`
   - File naming: Use numbered prefix for load order

2. **Is this explaining to humans?**
   - Keywords: "how it works", "guide", "tutorial", "overview"
   - Action: Create/update in `docs/` or appropriate markdown file
   - File naming: Descriptive, human-friendly names

3. **Is this both informational and actionable?**
   - Contains both explanation AND commands
   - Action: Mark with `<!-- Audience: Both -->` comment
   - Location: Choose based on primary purpose

### NEVER Mix These Patterns

❌ **Don't put enforcement language in human docs**

- Wrong: Adding "MUST always run tests" to README.md
- Right: That belongs in .claude/instructions/

❌ **Don't put long explanations in Claude instructions**

- Wrong: Educational content in CLAUDE.md
- Right: Keep instructions concise and directive

❌ **Don't put Claude behavior rules in human documentation**

- Wrong: "Claude should always..." in CONTRIBUTING.md
- Right: That belongs in .claude/instructions/

❌ **Don't put tutorials in .claude/**

- Wrong: Step-by-step guides in instruction files
- Right: Tutorials belong in docs/ or README

### When Updating Documentation

Follow this decision tree:

```text
Is this about Claude's behavior?
├─ YES → .claude/instructions/
│   ├─ New pattern? → Create new file or update relevant file
│   ├─ Existing rule change? → Update specific instruction file
│   └─ Core behavior? → Update 01-core-rules.md
│
└─ NO → Is this for humans?
    ├─ YES → docs/ or README.md
    │   ├─ API documentation? → docs/api/
    │   ├─ User guide? → docs/guides/
    │   └─ Contributing? → CONTRIBUTING.md
    │
    └─ NO → Is it both?
        ├─ Commands with explanation → Mark "Audience: Both"
        └─ Reference material → docs/ with executable examples
```

### File Organization in .claude/instructions/

Files are numbered for load order priority:

- `00-*` - Foundational (this file, core understanding)
- `01-*` - Core rules and enforcement
- `02-*` - Startup and context
- `03-*` - Required practices (MCP, etc.)
- `04-*` - Behavioral triggers (agents, etc.)
- `05-07-*` - Workflows and processes
- `08-*` - Project-specific configuration
- `09-10-*` - Tools and utilities

### Examples of Correct Placement

| Content Type | Example | Correct Location |
|-------------|---------|-----------------|
| Claude must never force-delete | Enforcement rule | `.claude/instructions/01-core-rules.md` |
| How MCP server works | Explanation | `docs/architecture.md` or `README.md` |
| When to use worktree-manager agent | Trigger pattern | `.claude/instructions/04-agent-triggers.md` |
| Project setup guide | Tutorial | `docs/setup.md` or `README.md` |
| Commit message format | Both (rule + example) | `.claude/instructions/06-workflow-commits.md` with examples |
| API endpoint documentation | Reference | `docs/api/` |
| TodoWrite tool usage rules | Claude behavior | `.claude/instructions/09-task-management.md` |

### Testing Your Understanding

When in doubt, ask yourself these questions:

1. "Would a human need to know this to use the project?" → docs/
2. "Do I (Claude) need this to behave correctly?" → .claude/instructions/
3. "Is this teaching or enforcing?" → Teaching=docs, Enforcing=.claude
4. "Would this work without Claude?" → If yes, probably docs/

### Remember

- **Claude instructions** = How you MUST behave
- **Human documentation** = How humans UNDERSTAND
- **Never mix** = Keep audiences separate
- **When updating** = Check audience first
- **Default to human docs** = When unclear, prefer docs/ over .claude/
