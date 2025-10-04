# Python Code Review Standards (2025)

## Goal

Ensure Python code follows industry best practices including PEP standards, modern Python features, type safety, testing standards, and avoids common anti-patterns. This workflow combines checklist-based review with PyEye's semantic analysis for intelligent code understanding.

## When to Use This Workflow

- Reviewing pull requests
- Code quality audits
- Onboarding code review training
- Pre-merge quality checks
- Learning modern Python best practices

## Standards Overview

This workflow enforces:

- **PEP 8** - Style guide for Python code
- **PEP 257** - Docstring conventions
- **PEP 484** - Type hints
- **Modern Python** - Features from 3.10, 3.11, 3.12+
- **Testing** - pytest best practices, 80%+ coverage
- **Security** - Basic security patterns

## Steps

1. **Run automated checks** - ruff, black, mypy, pytest with coverage
2. **Review code categories** - See detailed categories below:
   - Code Style & Formatting (PEP 8)
   - Type Safety & Type Hints (PEP 484)
   - Documentation (PEP 257)
   - Modern Python Features (3.10+)
   - Testing Best Practices
   - Common Anti-Patterns
   - Architecture & Design
   - Error Handling
   - Import Organization
   - Performance Considerations
3. **MCP-enhanced analysis** - Use semantic tools to understand code structure
4. **Manual code review** - Verify against checklist

## Review Categories

### 1. Code Style & Formatting (PEP 8)

**Automated Checks** (should be in CI):

- [ ] `ruff check` - Fast linter (replaces flake8)
- [ ] `black` - Code formatting
- [ ] `isort` - Import sorting

**Manual Review**:

- [ ] Naming follows PEP 8 conventions
  - Functions/variables: `snake_case`
  - Classes: `PascalCase`
  - Constants: `UPPER_CASE`
  - Private: `_leading_underscore`

**MCP Tool**: Use `get_module_info()` to see all exports and verify naming consistency:

```python
# Check module's public API naming
get_module_info(module_path="mypackage.module")
# Verify: exports, classes, functions follow conventions
```

### 2. Type Safety & Type Hints (PEP 484)

**Requirements**:

- [ ] All public functions have type hints
- [ ] Return types specified (even for `-> None`)
- [ ] Use modern generic syntax (Python 3.9+)
  - ✅ `list[str]` not `List[str]`
  - ✅ `dict[str, int]` not `Dict[str, int]`
  - ✅ `str | None` not `Optional[str]` (Python 3.10+)

**Static Type Checking**:

- [ ] `mypy` or `pyright` passes without errors
- [ ] No `# type: ignore` without justification

**MCP Tool**: Use `get_type_info()` to verify actual inferred types:

```python
# Check inferred type matches declared type
get_type_info(
    file="path/to/file.py",
    line=42,
    column=0,
    detailed=True
)
# Returns: inferred type, docstring, signature
```

**Common Type Hints Issues**:

```python
# ❌ BAD - Old generic syntax
from typing import List, Dict
def process(items: List[str]) -> Dict[str, int]:
    ...

# ✅ GOOD - Modern syntax (Python 3.9+)
def process(items: list[str]) -> dict[str, int]:
    ...

# ✅ GOOD - Union types (Python 3.10+)
def get_user(id: int) -> User | None:
    ...
```

### 3. Documentation (PEP 257)

**Docstring Requirements**:

- [ ] All public modules, classes, functions have docstrings
- [ ] Docstrings follow PEP 257 format
- [ ] Complex logic has inline comments

**Docstring Style** (Google/NumPy/Sphinx - be consistent):

```python
def calculate_score(user: User, items: list[Item]) -> float:
    """Calculate user score based on items.

    Args:
        user: User object containing profile data
        items: List of items to score

    Returns:
        float: Normalized score between 0 and 1

    Raises:
        ValueError: If user has no valid profile
    """
```

**MCP Tool**: Use `get_type_info(detailed=True)` to verify docstrings are present:

```python
# Check if function has proper documentation
get_type_info(file=path, line=line, column=col, detailed=True)
# Returns: docstring content for review
```

### 4. Modern Python Features (3.10+)

**Python 3.10+ Features to Use**:

- [ ] Pattern matching for complex conditionals
- [ ] Better error messages (already automatic)
- [ ] Union types with `|` operator
- [ ] Parenthesized context managers

**Python 3.11+ Features**:

- [ ] Exception groups and `except*`
- [ ] Performance improvements (CPython 10-60% faster)
- [ ] Better f-string support

**Python 3.12+ Features**:

- [ ] Type parameter syntax for generics
- [ ] F-string improvements (inline expressions)

**Examples**:

```python
# Python 3.10+ Pattern Matching
match response.status:
    case 200:
        return response.json()
    case 404:
        raise NotFoundError()
    case _:
        raise APIError(response.status)

# Python 3.10+ Union Types
def get_user(id: int) -> User | None:
    ...

# Python 3.11+ Exception Groups
try:
    ...
except* ValueError as e:
    handle_value_errors(e)
except* KeyError as e:
    handle_key_errors(e)
```

### 5. Testing Best Practices

**Coverage Requirements**:

- [ ] Minimum 80% code coverage (industry standard 2025)
- [ ] New code: 90%+ coverage
- [ ] Bug fixes: Include regression tests
- [ ] No tests for generated code only

**Test Quality**:

- [ ] Tests are independent (no shared state)
- [ ] Use pytest fixtures, not setup/teardown
- [ ] Avoid naive performance assertions
- [ ] Use descriptive test names

**Performance Testing** (CRITICAL):

```python
# ❌ BAD - Fails on slow CI
def test_search_speed():
    start = time.time()
    search(query)
    elapsed = time.time() - start
    assert elapsed < 0.2  # Fails on Windows CI!

# ✅ GOOD - Platform-aware thresholds
from tests.utils.performance import PerformanceThresholds, assert_performance_threshold

def test_search_speed():
    threshold = PerformanceThresholds(
        base=100.0,       # Local dev: 100ms
        linux_ci=150.0,   # Linux CI: 150ms
        macos_ci=300.0,   # macOS CI: 300ms
        windows_ci=300.0  # Windows CI: 300ms
    )
    with measure_time() as elapsed_ms:
        search(query)
    assert_performance_threshold(elapsed_ms, threshold, "search")
```

**MCP Tool**: Use `get_call_hierarchy()` to verify test coverage:

```python
# Find all callers of a function to see if tested
get_call_hierarchy(function_name="process_data")
# Check if test files are in callers list
```

### 6. Common Anti-Patterns to Avoid

**Mutable Default Arguments**:

```python
# ❌ BAD - Shared state between calls
def add_item(item, items=[]):
    items.append(item)
    return items

# ✅ GOOD - Create new list each time
def add_item(item, items=None):
    if items is None:
        items = []
    items.append(item)
    return items
```

**Using `is` for Value Comparison**:

```python
# ❌ BAD - Fragile, can break
if value is True:
    ...

# ✅ GOOD - Semantically correct
if value == True:
    ...
# Or better:
if value:
    ...
```

**God Functions/Objects**:

```python
# ❌ BAD - Does everything
def process_request(request):
    # Validation
    # Business logic
    # Database access
    # Response formatting
    # Logging
    # Error handling
    pass

# ✅ GOOD - Single responsibility
def process_request(request):
    validate_request(request)
    data = apply_business_logic(request)
    save_to_database(data)
    return format_response(data)
```

**Reinventing the Wheel**:

```python
# ❌ BAD - Custom JSON parser
def parse_json(text):
    # Custom implementation
    ...

# ✅ GOOD - Use standard library
import json
data = json.loads(text)
```

**MCP Tool**: Use `find_references()` to spot code duplication:

```python
# Find similar functions that might be duplicated logic
find_references(file=path, line=line, column=col)
# If many references do similar things, consider extracting common logic
```

### 7. Architecture & Design

**SOLID Principles**:

- [ ] Single Responsibility - Each class/function does one thing
- [ ] Open/Closed - Open for extension, closed for modification
- [ ] Liskov Substitution - Subclasses work where base class expected
- [ ] Interface Segregation - Many specific interfaces vs. one general
- [ ] Dependency Inversion - Depend on abstractions, not concretions

**MCP Tools for Architecture Review**:

```python
# Check inheritance hierarchy
find_subclasses(base_class="BaseProcessor", show_hierarchy=True)
# Verify: Subclasses follow Liskov Substitution

# Check module dependencies
analyze_dependencies(module_path="mypackage.core")
# Verify: No circular dependencies, clean architecture layers

# Check what uses this module
find_imports(module_name="mypackage.core")
# Verify: Only appropriate modules depend on core
```

### 8. Error Handling

**Best Practices**:

- [ ] Use specific exceptions, not bare `except:`
- [ ] Raise exceptions with context
- [ ] Use custom exceptions for domain errors
- [ ] Log errors appropriately

```python
# ❌ BAD - Swallows all errors
try:
    process_data()
except:
    pass

# ✅ GOOD - Specific handling
try:
    process_data()
except ValueError as e:
    logger.error(f"Invalid data: {e}")
    raise DataProcessingError(f"Failed to process: {e}") from e
```

### 9. Import Organization

**Order** (PEP 8):

1. Standard library
2. Third-party libraries
3. Local application imports

**Tool**: Use `isort` to automatically organize imports

**MCP Tool**: Use `get_module_info()` to review imports:

```python
get_module_info(module_path="mypackage.module")
# Returns: imports_from list for review
# Check: Appropriate dependencies, no circular imports
```

### 10. Performance Considerations

**General Guidelines**:

- [ ] Use list comprehensions over loops (when clearer)
- [ ] Use generators for large datasets
- [ ] Avoid premature optimization
- [ ] Profile before optimizing

```python
# ✅ GOOD - List comprehension
squares = [x**2 for x in range(100)]

# ✅ GOOD - Generator for large data
def read_large_file(path):
    with open(path) as f:
        for line in f:
            yield process_line(line)
```

**MCP Tool**: Use `get_call_hierarchy()` to understand performance:

```python
# Trace execution to find bottlenecks
get_call_hierarchy(function_name="slow_operation")
# Returns: callers and callees - helps identify hot paths
```

## Review Workflow

### Step 1: Automated Checks

Run tools (should be in CI):

```bash
ruff check .           # Linting
black --check .        # Format check
mypy .                # Type checking
pytest --cov=src --cov-fail-under=80  # Tests + coverage
```

### Step 2: MCP-Enhanced Analysis

**For New Classes**:

1. `find_symbol()` - Locate class definition
2. `get_type_info(detailed=True)` - Check documentation, structure
3. `find_subclasses()` - See if it follows inheritance patterns
4. `find_references()` - Review usage patterns

**For New Functions**:

1. `find_symbol()` - Locate function
2. `get_type_info(detailed=True)` - Check types, docs
3. `get_call_hierarchy()` - Understand execution flow
4. `find_references()` - Review how it's used

**For Modules**:

1. `get_module_info()` - Review structure, exports
2. `analyze_dependencies()` - Check for circular deps
3. `find_imports()` - See what depends on it

### Step 3: Manual Code Review

Review against checklist above:

- Code style and naming
- Type hints completeness
- Documentation quality
- Modern Python usage
- Test coverage and quality
- Anti-pattern avoidance
- Architecture compliance

### Step 4: Context Understanding

Use **[Code Understanding Workflow](workflows://code-understanding)** to deeply understand changes before approving.

## Complete Review Example

**Scenario**: Reviewing a new `DataProcessor` class

### Automated Analysis

```bash
✅ ruff check - passed
✅ black --check - passed
✅ mypy - passed
✅ pytest --cov - 92% coverage
```

### MCP-Enhanced Review

```python
# 1. Locate and inspect
find_symbol(name="DataProcessor")
→ Found at: src/processing/processor.py:45

get_type_info(file="src/processing/processor.py", line=45, detailed=True)
→ Class with proper docstring ✅
→ Inherits from BaseProcessor ✅
→ Has type hints ✅
→ Methods: process, validate, transform ✅

# 2. Check architecture
find_subclasses(base_class="BaseProcessor", show_hierarchy=True)
→ DataProcessor follows established pattern ✅

analyze_dependencies(module_path="processing.processor")
→ No circular dependencies ✅
→ Imports: typing, pathlib, logging (appropriate) ✅

# 3. Review usage
find_references(file="src/processing/processor.py", line=45)
→ Used in 5 places, all appropriate ✅
→ Test coverage exists ✅

# 4. Check call flow
get_call_hierarchy(function_name="process")
→ Calls validate → transform → save ✅
→ Called by batch_processor, api_handler ✅
```

### Manual Review Findings

- ✅ Naming follows PEP 8
- ✅ Type hints use modern syntax (`list[str]` not `List[str]`)
- ✅ Docstrings follow Google style
- ✅ Uses Python 3.10+ features (union types)
- ✅ Tests are independent, use fixtures
- ✅ No anti-patterns detected
- ✅ Follows single responsibility principle

**Result**: APPROVED ✅

## Quick Reference Checklist

**Before Approval**:

- [ ] All automated checks pass (ruff, black, mypy, tests)
- [ ] Used MCP tools for semantic analysis
- [ ] Type hints complete and modern
- [ ] Documentation adequate (PEP 257)
- [ ] Tests independent with good coverage (80%+)
- [ ] No anti-patterns or code smells
- [ ] Architecture follows SOLID principles
- [ ] Modern Python features used appropriately

## Success Indicators

✅ **Automated tools pass** - No linting, format, or type errors
✅ **Semantic analysis complete** - Used MCP tools to understand relationships
✅ **Standards compliant** - Follows PEP 8, 257, 484
✅ **Modern Python** - Uses 3.10+ features appropriately
✅ **Well tested** - 80%+ coverage, independent tests
✅ **Well documented** - Clear docstrings and comments
✅ **Clean architecture** - No circular deps, SOLID principles

## Related Workflows

- [Security Review](workflows://code-review-security) - OWASP security checklist
- [PR Review](workflows://code-review-pr) - Complete pull request review
- [Code Understanding](workflows://code-understanding) - Deep dive into unfamiliar code
- [Refactoring](workflows://refactoring) - Safe code changes

## Tools & Resources

**Linters & Formatters**:

- `ruff` - Fast Python linter (replaces flake8, isort, pyupgrade)
- `black` - Opinionated code formatter
- `mypy` / `pyright` - Static type checkers

**Testing**:

- `pytest` - Testing framework
- `pytest-cov` - Coverage plugin
- `coverage.py` - Coverage measurement

**References**:

- [PEP 8 - Style Guide](https://peps.python.org/pep-0008/)
- [PEP 257 - Docstrings](https://peps.python.org/pep-0257/)
- [PEP 484 - Type Hints](https://peps.python.org/pep-0484/)
- [Python Anti-Patterns](https://docs.quantifiedcode.com/python-anti-patterns/)
- [Real Python - Code Quality](https://realpython.com/python-code-quality/)

## Project-Specific Overrides

Add project-specific standards here as needed:

- Custom naming conventions
- Framework-specific patterns
- Domain-specific requirements
- Performance thresholds
- Security requirements
