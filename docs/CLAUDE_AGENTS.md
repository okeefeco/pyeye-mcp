# Claude Code Agents for Python Intelligence MCP

This document describes the specialized Claude Code agents (subagents) that leverage our Python Intelligence MCP tools for enhanced development workflows.

## Overview

These agents appear in Claude Code's `/agents` command and provide specialized capabilities by leveraging our semantic code analysis tools. Unlike regular Python scripts, these are true Claude Code subagents that run in separate contexts to preserve your main session.

## Available Agents

### 🔍 cross-platform-validator

**Purpose**: Validates and fixes cross-platform compatibility issues to prevent OS-specific CI failures.

**Key Features**:

- **Extensible Framework**: Modular issue detection that grows over time
- **Current**: Path separator issues (fully implemented)
- **Planned**: File permissions, line endings, shell commands, temp dirs, encoding
- **Learning System**: Tracks CI failure patterns to prioritize fixes
- **MCP-Powered**: Uses semantic analysis, not regex patterns

**Configuration**: See `.claude/agents/cross-platform-issues.yaml` for issue types

**Usage**:

```bash
# Via Task tool
Task(
    subagent_type="cross-platform-validator",
    prompt="Check cross-platform compatibility in src/"
)

# Or use /agents command and select it
```

**Natural Language Commands**:

- "Check cross-platform compatibility"
- "Fix path issues in cache module"
- "Validate path handling for Windows"
- "Review this PR for path problems"
- "Ensure Windows CI will pass"

**What It Fixes**:

1. `str(Path)` in API responses → `.as_posix()`
2. Direct path comparisons → `paths_equal()`
3. Path dictionary keys → `path_to_key()`
4. Template/config paths → `.as_posix()`

## How Agents Work

### Architecture

1. **Separate Context**: Agents run in isolated Claude contexts, preserving your main session
2. **MCP Integration**: All agents use `mcp__python-intelligence__*` tools exclusively
3. **Semantic Analysis**: No regex or AST parsing - pure semantic understanding
4. **Tool Restrictions**: Each agent only has access to specified tools

### File Structure

```text
.claude/agents/
├── cross-platform-validator.md    # Path compatibility agent
├── test-coverage-enhancer.md      # (planned) Test generation agent
├── refactoring-assistant.md       # (planned) Safe refactoring agent
└── dependency-analyzer.md         # (planned) Dependency analysis agent
```

### Agent Definition Format

```markdown
---
name: agent-name
description: "Brief description of what the agent does"
tools: tool1, tool2, tool3  # Specific tools the agent can use
---

[Agent system prompt with detailed instructions]
```

## Creating New Agents

### Development Workflow with Worktrees

When developing agents in a worktree, the `/agents` command won't see them (it looks in current directory's `.claude/agents/`). Options:

1. **Symlink for Testing**:

```bash
# Link worktree agent to main repo
ln -s ../python-code-intelligence-mcp-work/feat-X/.claude/agents/my-agent.md .claude/agents/
```

1. **Work in Worktree**:

```bash
cd ../python-code-intelligence-mcp-work/feat-X
# Now /agents will show your agent
```

1. **Direct Task Invocation** (works from anywhere):

```python
Task(
    subagent_type="general-purpose",
    prompt="Use agent from [path]"
)
```

### Step 1: Define the Agent

Create a file in `.claude/agents/` with YAML frontmatter:

```markdown
---
name: my-custom-agent
description: "What this agent does"
tools: mcp__python-intelligence__find_symbol, Read, Edit
---

You are a specialized agent for [specific task]...
```

### Step 2: Leverage MCP Tools

Ensure your agent uses semantic analysis:

```python
# ✅ GOOD: Semantic understanding
mcp__python-intelligence__find_symbol("ClassName")
mcp__python-intelligence__get_type_info(file, line, col)
mcp__python-intelligence__find_references(file, line, col)

# ❌ BAD: Text pattern matching
grep("class ClassName")
re.search(r"def \w+", code)
```

### Step 3: Test the Agent

1. Run `/agents` to see your new agent
2. Test with sample commands
3. Verify it uses MCP tools (check metrics)

## Best Practices

### 1. Focused Responsibility

Each agent should have a single, clear purpose:

- ✅ "Cross-platform path validator"
- ❌ "General code fixer"

### 2. MCP-First Approach

Always use semantic understanding over text matching:

- Use `find_symbol` not `grep`
- Use `get_type_info` to verify types
- Use `find_references` before refactoring

### 3. Clear Output

Provide concise, actionable summaries:

```markdown
## Report
- Found: X issues
- Fixed: Y files
- Status: ✅ All tests passing
```

### 4. Natural Language Interface

Support intuitive commands:

- "Check [something]"
- "Fix [issue] in [location]"
- "Validate [aspect]"
- "Review [code] for [problem]"

## Testing Agents

### Manual Testing

1. Create test scenarios:

```bash
python scripts/test_cross_platform_agent.py
```

1. Invoke the agent:

```python
Task(
    subagent_type="cross-platform-validator",
    prompt="Check the test files"
)
```

1. Verify results

### Automated Validation

Agents should be tested for:

- Correct issue detection
- Appropriate fix generation
- No false positives
- MCP tool usage (not grep/regex)

## Metrics and Monitoring

Track agent effectiveness:

```python
# Check MCP usage
mcp__python-intelligence__get_performance_metrics()

# Verify semantic operations
# Should see find_symbol, get_type_info, etc.
# Should NOT see grep, ast.parse, etc.
```

## Planned Agents

### test-coverage-enhancer

- Analyzes code coverage gaps
- Generates tests following project patterns
- Handles framework-specific testing

### refactoring-assistant

- Safe symbol renaming
- Method extraction
- Dead code removal
- Always uses find_references first

### dependency-analyzer

- Circular dependency detection
- Impact analysis for changes
- Architecture recommendations

## Benefits of Agent Approach

1. **Context Preservation**: Main session isn't cluttered with analysis
2. **Specialized Expertise**: Each agent is an expert in its domain
3. **Tool Safety**: Agents only have necessary permissions
4. **Reusability**: Agents can be shared across projects
5. **Dogfooding**: We use our own tools to improve our tools

## Troubleshooting

### Agent Not Appearing in /agents

1. Check file location: `.claude/agents/`
2. Verify YAML frontmatter format
3. Ensure unique agent name
4. Restart Claude Code if needed

### Agent Not Using MCP Tools

1. Verify tools are listed in frontmatter
2. Check agent prompt emphasizes MCP usage
3. Review agent's actual tool calls

### Poor Performance

1. Agent might be using text search instead of semantic analysis
2. Check `get_performance_metrics()` for MCP usage
3. Refine agent prompt to prioritize MCP tools

## Extensibility: Growing Agent Capabilities

### The Incremental Approach

Our agents start focused and expand over time based on real needs:

1. **Start Specific**: Begin with most common/critical issues
2. **Learn from CI**: Track what actually causes failures
3. **Add Modularly**: New issue types don't affect existing ones
4. **Prioritize by Impact**: Focus on issues that matter most

### Example: Cross-Platform Validator Evolution

```yaml
# Phase 1 (Current): Path issues - 45% of Windows CI failures
path_separators: enabled

# Phase 2 (Next): Based on CI data showing next pain points
file_permissions: enabled  # 20% of failures
line_endings: enabled      # Frequent PR issues

# Phase 3: Shell/system issues
shell_commands: enabled
temp_directories: enabled

# Future: As needed
encoding, process_handling, symlinks, etc.
```

### Adding New Capabilities to Existing Agents

1. **Update Configuration** (`cross-platform-issues.yaml`):

```yaml
new_issue_type:
  enabled: false  # Start disabled
  priority: medium
  description: "What this detects"
  mcp_detection:
    - find_symbol: ["relevant_symbols"]
```

1. **Implement Detection** (in agent prompt):

- Add MCP-based detection logic
- Define fix patterns
- Test on real code

1. **Enable When Ready**:

- Set `enabled: true`
- Document in CLAUDE_AGENTS.md
- Track effectiveness

### Benefits of This Approach

- **Low Risk**: New features don't break existing ones
- **Data-Driven**: Expand based on actual CI failures
- **Maintainable**: Each issue type is independent
- **Learnable**: Track what works and what doesn't

## Contributing

To contribute to agents:

### Extending Existing Agents

1. Identify gaps from CI failures or user feedback
2. Add issue type to configuration
3. Implement MCP-based detection
4. Test and validate
5. Submit PR with examples

### Creating New Agents

1. Identify a repetitive task that could be automated
2. Design the agent to use MCP tools exclusively
3. Create the agent definition
4. Add documentation here
5. Submit PR with example usage

Remember: The goal is to showcase how semantic understanding (via MCP) surpasses simple pattern matching for complex development tasks.
