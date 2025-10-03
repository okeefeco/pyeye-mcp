# Test Coverage Enhancement Agent - Usage Guide

## Overview

The Test Coverage Enhancement Agent is a Claude Code sub-agent that systematically analyzes test coverage gaps using semantic code understanding via MCP tools, then automatically generates comprehensive tests following project patterns.

## Key Features

- **100% MCP-Powered**: Uses PyEye tools exclusively - no AST parsing or grep
- **Semantic Understanding**: Understands code meaning, not just text patterns
- **Pattern Learning**: Discovers and follows existing test conventions
- **Framework-Aware**: Special handling for Pydantic, Flask, Django
- **Context-Efficient**: Runs in separate Claude context to preserve main session

## How to Use with Claude Task Tool

### Basic Usage

When you want to improve test coverage, invoke the agent using Claude's Task tool:

```python
# In main Claude session, use the Task tool:
Task(
    description="Improve test coverage",
    prompt="Improve test coverage for the cache module to 90%",
    subagent_type="general-purpose"
)
```

### Natural Language Commands

The agent understands various natural language requests:

- "Improve test coverage for cache module"
- "Add missing test cases for async_utils.py"
- "Bring test coverage up to 90% for validation module"
- "Generate regression tests for the import bug"
- "Add edge case tests for the ProjectManager class"
- "Create performance tests for find_symbol function"

### What Happens When Invoked

1. **Context Separation**: Agent runs in separate context, preserving main session
2. **Semantic Analysis**: Uses MCP tools to understand code structure
3. **Pattern Recognition**: Learns how tests are currently written
4. **Test Generation**: Creates tests matching project style
5. **Concise Return**: Returns summary to main session

## MCP Tool Usage Flow

### Phase 1: Discovery (Finding Gaps)

```python
# Agent uses these MCP tools to find untested code:
mcp__pyeye__list_modules()           # Get project structure
mcp__pyeye__find_symbol("def")       # Find all functions
mcp__pyeye__find_symbol("class")     # Find all classes
mcp__pyeye__find_references()        # Check if tested
```

### Phase 2: Pattern Analysis

```python
# Agent learns existing test patterns:
mcp__pyeye__find_subclasses("TestCase")   # Test classes
mcp__pyeye__find_symbol("test_", fuzzy=True)  # Test functions
mcp__pyeye__find_imports("pytest")        # Framework detection
mcp__pyeye__find_symbol("fixture")        # Fixture patterns
```

### Phase 3: Semantic Generation

```python
# Agent generates tests using understanding:
mcp__pyeye__get_type_info()          # Function signatures
mcp__pyeye__find_references()        # Usage patterns
mcp__pyeye__get_call_hierarchy()     # Mock requirements
mcp__pyeye__analyze_dependencies()   # Import needs
```

### Phase 4: Framework-Specific

```python
# For framework-specific code:
mcp__pyeye__find_models()            # Pydantic models
mcp__pyeye__get_model_schema()       # Model structure
mcp__pyeye__find_routes()            # Flask endpoints
mcp__pyeye__find_validators()        # Validation logic
```

## Example Interaction

### User Request

```text
"I need to improve test coverage for the async_utils module.
We're currently at 60% and need to reach 85%. Focus on edge cases."
```

### Agent Execution (via Task tool)

1. **Discovery Phase**
   - Finds 12 functions in async_utils
   - Identifies 5 untested functions
   - Locates 3 partially tested functions

2. **Pattern Analysis**
   - Detects pytest as test framework
   - Finds test naming pattern: `test_{function_name}_{scenario}`
   - Identifies asyncio fixture usage
   - Discovers mock patterns for external calls

3. **Test Generation**
   - Generates tests for 5 untested functions
   - Adds edge cases for 3 partial functions
   - Uses discovered patterns:

     ```python
     @pytest.mark.asyncio
     async def test_batch_operation_empty_list():
         """Test batch_operation with empty input."""
         result = await batch_operation([])
         assert result == []
     ```

4. **Validation**
   - Verifies all imports exist
   - Checks naming conventions
   - Ensures no circular dependencies

### Agent Response to Main Session

```json
{
  "summary": "Found 8 coverage gaps | Generated 15 tests | Expected +25% coverage | 95% semantic analysis",
  "details": {
    "untested_functions": 5,
    "edge_cases_added": 10,
    "test_files_created": 2,
    "patterns_followed": ["pytest", "async", "fixture", "mock"]
  },
  "mcp_adoption": "95%",
  "next_steps": [
    "Review generated tests in tests/test_async_utils_generated.py",
    "Run pytest to verify all tests pass",
    "Check coverage report for improvement"
  ]
}
```

## Benefits Over Manual Testing

### Speed

- **Manual**: 2-3 hours to write 15 tests
- **Agent**: 2-3 minutes for analysis and generation

### Quality

- **Semantic Understanding**: Tests based on actual usage patterns
- **Pattern Consistency**: All tests follow project conventions
- **Edge Case Discovery**: Finds cases humans might miss

### MCP Advantages

- **No False Positives**: Semantic understanding vs text matching
- **Framework Awareness**: Knows Pydantic, Flask, Django patterns
- **Usage-Based**: Tests reflect how code is actually used

## Advanced Usage

### Targeting Specific Areas

```python
# Focus on async functions
"Generate tests for all async functions in the connection_pool module"

# Target specific class
"Add comprehensive tests for the ProjectManager class"

# Framework-specific
"Create validation tests for all Pydantic models"
"Generate endpoint tests for Flask routes"
```

### Regression Testing

```python
# After fixing a bug
"Generate regression tests for the import resolution bug in issue #145"
```

### Performance Testing

```python
# Using project's performance framework
"Add performance tests for find_symbol using PerformanceThresholds"
```

## Integration with CI/CD

The agent generates tests that:

- Follow project's pre-commit hooks
- Pass linting (black, ruff, mypy)
- Include proper type hints
- Have descriptive docstrings
- Use project's assertion style

## Metrics and Reporting

### MCP Usage Metrics

- **Tool Calls**: Number of MCP operations
- **Semantic Accuracy**: % using semantic vs text analysis
- **Pattern Matching**: How well generated tests match existing

### Coverage Metrics

- **Gaps Found**: Untested symbols discovered
- **Tests Generated**: Number of new tests
- **Expected Improvement**: Estimated coverage increase

## Troubleshooting

### "Cannot find module"

- Ensure module path is correct
- Check if module is in configured packages
- Use fully qualified import path

### "No patterns detected"

- Project may not have enough existing tests
- Agent will use sensible defaults
- Consider providing example test for pattern learning

### "Generated tests fail"

- Check if all dependencies are installed
- Verify mock objects are correctly configured
- Ensure test database/fixtures are available

## Best Practices

1. **Run on Clean Branch**: Ensure working directory is clean
2. **Review Generated Tests**: Agent output should be reviewed
3. **Run Tests Locally**: Verify tests pass before committing
4. **Check Coverage**: Confirm coverage improvement met
5. **Iterate if Needed**: Can run multiple times for different focuses

## Conclusion

The Test Coverage Enhancement Agent demonstrates the power of semantic code understanding through MCP tools. By dogfooding our own PyEye, we show that AI can understand code well enough to test it properly - not through pattern matching, but through true semantic comprehension.
