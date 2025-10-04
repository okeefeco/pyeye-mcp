# Complete Pull Request Review Workflow

## Goal

Perform comprehensive pull request reviews combining automated checks, semantic analysis, code standards, and security review. This workflow ensures code quality, safety, and maintainability before merging to main.

## When to Use This Workflow

- Reviewing pull requests before merge
- Final quality gate before deployment
- Team code review process
- Pre-release validation
- Learning comprehensive review practices

## PR Review Philosophy

**Effective code review balances**:

- **Speed** - Don't block progress unnecessarily
- **Quality** - Catch issues before they reach production
- **Learning** - Help team improve skills
- **Automation** - Let tools handle mechanical checks

**This workflow emphasizes**:

- Automated checks catch mechanical issues
- Semantic analysis reveals hidden problems
- Manual review focuses on design and logic
- Constructive feedback promotes growth

## Complete Review Process

### Phase 1: Automated Analysis (5 minutes)

**CI Must Pass** (blocking):

- [ ] All tests pass
- [ ] Code coverage meets threshold (80%+)
- [ ] Linting passes (ruff, black)
- [ ] Type checking passes (mypy)
- [ ] Security scans pass (bandit, pip-audit, detect-secrets)

**Quick Check**:

```bash
# View CI status
gh pr checks

# Run locally if needed
pytest --cov=src --cov-fail-under=80
ruff check .
mypy .
```

**If CI Fails**: Request fixes before manual review

### Phase 2: PR Context Understanding (10 minutes)

**Read the PR**:

- [ ] Read PR description and linked issue
- [ ] Understand the goal and motivation
- [ ] Note any special considerations
- [ ] Check if breaking changes mentioned

**Identify Changed Components**:

```bash
# View changed files
gh pr diff

# Check what modules are affected
git diff main...HEAD --name-only
```

**MCP Tool - Quick Scope Analysis**:

```python
# For each major changed file, understand context
get_module_info(module_path="changed.module")
# Returns: structure, exports, imports

# Check what depends on changed code
analyze_dependencies(module_path="changed.module")
# Returns: who imports this, circular deps
```

### Phase 3: Semantic Impact Analysis (15 minutes)

**For Each Significant Change**:

#### If New Class Added

```python
# 1. Understand the class
find_symbol(name="NewClass")
get_type_info(file=..., line=..., detailed=True)
# Check: Documentation, structure, patterns

# 2. Check if follows architecture
find_subclasses(base_class="ParentClass", show_hierarchy=True)
# Verify: Inheritance hierarchy makes sense

# 3. Review usage
find_references(file=..., line=...)
# Check: Used correctly, not overused
```

#### If Function Modified

```python
# 1. Find all call sites
find_references(file=..., line=function_line)
# Verify: All callers still work with changes

# 2. Check execution flow
get_call_hierarchy(function_name="modified_function")
# Verify: Call chain still makes sense

# 3. For breaking changes
# Ensure all callers are updated in this PR
```

#### If Refactoring/Rename

```python
# Use the Refactoring Workflow
# workflows://refactoring

# 1. Find all usages
find_references(file=old_location, line=old_line)
# Verify: ALL references updated

# 2. Check subclasses (if class)
find_subclasses(base_class="OldName")
# Verify: Subclasses still work

# 3. Check dependencies
analyze_dependencies(module_path="refactored.module")
# Verify: No broken imports
```

### Phase 4: Code Standards Review (10 minutes)

**Use Standards Workflow**: [workflows://code-review-standards](workflows://code-review-standards)

**Key Checks**:

- [ ] Naming follows PEP 8 conventions
- [ ] Type hints complete and modern (Python 3.9+ syntax)
- [ ] Docstrings follow PEP 257
- [ ] Modern Python features used (3.10+)
- [ ] No anti-patterns (mutable defaults, god functions, etc.)
- [ ] Tests are independent and comprehensive

**Quick MCP Checks**:

```python
# Check naming consistency
get_module_info(module_path="new.module")
# Review: exports follow naming conventions

# Verify type safety
get_type_info(file=..., line=..., detailed=True)
# Check: Type hints present and correct
```

### Phase 5: Security Review (15 minutes)

**Use Security Workflow**: [workflows://code-review-security](workflows://code-review-security)

**Critical Security Checks**:

- [ ] Input validation on all user data
- [ ] No SQL/command injection vulnerabilities
- [ ] Passwords properly hashed
- [ ] No hardcoded secrets
- [ ] Dependencies scanned (pip-audit, safety)

**For High-Risk Changes**:

```python
# Trace data flow for security
get_call_hierarchy(function_name="handle_user_input")
# Verify: Input validated, output sanitized

# Check authentication
find_symbol(name="auth", fuzzy=True)
find_references(...)
# Verify: Auth checked on protected resources
```

### Phase 6: Testing Review (10 minutes)

**Test Quality Checks**:

- [ ] New code has tests (90%+ coverage)
- [ ] Bug fixes have regression tests
- [ ] Tests are independent (no shared state)
- [ ] Performance tests use proper thresholds
- [ ] Edge cases covered

**MCP Tool - Test Coverage**:

```python
# Find what tests the new code
find_references(file=new_code_file, line=new_function_line)
# Check: Test files in references

# Understand test structure
get_call_hierarchy(function_name="test_new_feature")
# Verify: Tests cover main paths
```

**Common Testing Issues**:

```python
# ❌ BAD - Naive performance test
assert elapsed < 0.2  # Fails on slow CI!

# ✅ GOOD - Platform-aware thresholds
from tests.utils.performance import PerformanceThresholds
assert_performance_threshold(elapsed_ms, threshold, "operation")
```

### Phase 7: Architecture & Design Review (15 minutes)

**Design Principles**:

- [ ] Single Responsibility - Each class/function does one thing
- [ ] DRY - No duplicated code
- [ ] SOLID principles followed
- [ ] Clean architecture layers
- [ ] No circular dependencies

**MCP Tools for Architecture**:

```python
# Check for circular dependencies
analyze_dependencies(module_path="new.module")
# Flag: circular_dependencies list should be empty

# Verify clean module boundaries
find_imports(module_name="core.module")
# Check: Only appropriate modules import core

# Review inheritance hierarchy
find_subclasses(base_class="NewBase", show_hierarchy=True)
# Verify: Hierarchy makes sense, not too deep
```

### Phase 8: Manual Code Review (20 minutes)

**Focus Areas**:

**Logic & Correctness**:

- [ ] Algorithm is correct
- [ ] Edge cases handled
- [ ] Error handling appropriate
- [ ] Resource cleanup (context managers)

**Readability**:

- [ ] Code is self-documenting
- [ ] Complex logic has comments
- [ ] Variable names are clear
- [ ] Function length reasonable (<50 lines)

**Performance**:

- [ ] No obvious inefficiencies
- [ ] Appropriate data structures
- [ ] Database queries optimized
- [ ] Caching considered if needed

**Maintainability**:

- [ ] Easy to modify in future
- [ ] Clear separation of concerns
- [ ] Dependencies justified
- [ ] Technical debt noted/addressed

## Complete PR Review Example

**Scenario**: Review PR adding user profile API endpoint

### 1. Automated Checks (2 min)

```bash
gh pr checks
✅ Tests: 156 passed
✅ Coverage: 94% (+2% from base)
✅ Linting: passed
✅ Type checking: passed
✅ Security: passed
```

### 2. Context Understanding (5 min)

```text
PR #247: Add user profile API endpoint
- Adds GET /api/users/{id}/profile
- Returns user profile with privacy settings
- Linked to issue #245
```

Changed files:

- `api/users.py` - New endpoint
- `models/profile.py` - Profile model
- `tests/test_users_api.py` - Tests

### 3. Semantic Analysis (10 min)

```python
# Understand new endpoint
find_symbol(name="get_user_profile")
→ Found at: api/users.py:67

get_type_info(file="api/users.py", line=67, detailed=True)
→ Function: get_user_profile(user_id: int) -> ProfileResponse
→ Docstring: Complete ✅
→ Type hints: Present ✅

# Check execution flow
get_call_hierarchy(function_name="get_user_profile")
→ Calls: get_user, check_privacy_settings, format_profile ✅
→ Called by: api_router (FastAPI) ✅

# Verify model structure
get_module_info(module_path="models.profile")
→ Exports: ProfileModel, PrivacySettings ✅
→ Imports: pydantic, enum ✅

# Check who uses the model
find_references(file="models/profile.py", line=profile_model_line)
→ Used in: api/users.py, serializers.py, tests ✅
→ All references appropriate ✅
```

### 4. Code Standards (5 min)

```text
✅ Naming: snake_case functions, PascalCase classes
✅ Type hints: Modern syntax (ProfileModel | None)
✅ Docstrings: Google style, complete
✅ No anti-patterns detected
✅ Uses Python 3.10+ features (union types)
```

### 5. Security Review (10 min)

```python
# Check authorization
find_symbol(name="get_user_profile")
→ Has @require_auth decorator ✅

# Trace user_id input
get_call_hierarchy(function_name="get_user_profile")
→ user_id validated as int (FastAPI) ✅
→ No SQL injection risk (ORM used) ✅

# Check privacy logic
→ check_privacy_settings() verifies access ✅
→ Returns 403 if unauthorized ✅

# No secrets in code
→ detect-secrets passed ✅
```

### 6. Testing Review (5 min)

```python
# Check test coverage
find_references(file="api/users.py", line=67)
→ test_get_user_profile_success ✅
→ test_get_user_profile_not_found ✅
→ test_get_user_profile_unauthorized ✅
→ test_get_user_profile_privacy ✅

# Verify test quality
# Tests are independent ✅
# Edge cases covered (not found, unauthorized) ✅
# Privacy scenarios tested ✅
```

### 7. Architecture Review (5 min)

```python
# Check dependencies
analyze_dependencies(module_path="api.users")
→ Imports: models.profile, services.auth ✅
→ No circular dependencies ✅

# Verify layering
→ API → Services → Models ✅
→ Clean separation of concerns ✅
```

### 8. Manual Review Findings

- ✅ Logic correct, handles edge cases
- ✅ Error handling appropriate (404, 403)
- ✅ Resource cleanup (async context manager)
- ✅ Privacy logic well-structured
- ⚠️ Minor: Could use constant for privacy levels
- 💡 Suggestion: Consider caching for frequently accessed profiles

**Review Decision**: ✅ APPROVE with suggestions

**Feedback**:

```markdown
Great work! This PR is well-structured and secure.

**Strengths:**
- Comprehensive test coverage (94%)
- Proper authorization checks
- Clean code structure
- Good error handling

**Suggestions:**
1. Consider extracting privacy levels to constants/enum for maintainability
2. Profile data might benefit from caching (Redis) for high-traffic users
3. Consider adding rate limiting to prevent abuse

**Security:** ✅ Verified authorization, input validation, and privacy controls

Approved pending minor suggestion #1 (not blocking).
```

## Review Checklist Template

### Automated (CI Required)

- [ ] All tests pass
- [ ] Coverage meets threshold (80%+)
- [ ] Linting passes
- [ ] Type checking passes
- [ ] Security scans pass

### Semantic Analysis (MCP Tools)

- [ ] Used `find_references()` for changed symbols
- [ ] Used `get_call_hierarchy()` to understand flow
- [ ] Used `analyze_dependencies()` for module changes
- [ ] Used `find_subclasses()` for class changes

### Code Standards

- [ ] Follows PEP 8, 257, 484
- [ ] Uses modern Python features
- [ ] No anti-patterns
- [ ] Proper documentation

### Security

- [ ] Input validation present
- [ ] No injection vulnerabilities
- [ ] Authorization checked
- [ ] No secrets in code

### Testing

- [ ] New code tested (90%+)
- [ ] Tests independent
- [ ] Edge cases covered
- [ ] Bug fixes have regression tests

### Architecture

- [ ] SOLID principles followed
- [ ] No circular dependencies
- [ ] Clean module boundaries
- [ ] Appropriate design patterns

### Manual Review

- [ ] Logic correctness
- [ ] Error handling
- [ ] Performance considerations
- [ ] Maintainability

## Review Outcomes

### Approve ✅

When to approve:

- All automated checks pass
- Semantic analysis shows no issues
- Standards and security verified
- High quality, maintainable code

### Request Changes 🔄

When to request changes:

- Security vulnerabilities
- Broken functionality
- Architectural violations
- Missing tests

### Comment/Suggest 💬

When to comment:

- Nice-to-have improvements
- Alternative approaches
- Learning opportunities
- Future considerations

## Constructive Feedback Guidelines

**Be Specific**:

- ❌ "This code is messy"
- ✅ "Consider extracting lines 45-60 into a separate function for clarity"

**Explain Why**:

- ❌ "Don't use this pattern"
- ✅ "This pattern can lead to memory leaks because... Consider using a context manager instead"

**Offer Solutions**:

- ❌ "This won't scale"
- ✅ "For large datasets, consider using a generator: `for item in (x for x in items if x.active)`"

**Acknowledge Good Work**:

- ✅ "Great test coverage on edge cases!"
- ✅ "Nice use of type hints here"
- ✅ "This abstraction makes the code much clearer"

## Time Budget

**Small PR** (<100 lines): 15-20 minutes

- Automated: 2 min
- Context: 3 min
- Semantic: 5 min
- Standards: 3 min
- Security: 2 min
- Manual: 5 min

**Medium PR** (100-500 lines): 30-45 minutes

- Automated: 5 min
- Context: 5 min
- Semantic: 15 min
- Standards: 5 min
- Security: 5 min
- Manual: 10 min

**Large PR** (500+ lines): 1-2 hours

- Consider requesting split into smaller PRs
- Focus on architecture and high-level design
- May need multiple review sessions

## Common Review Mistakes

1. **Focusing on style over substance** - Let linters handle style
2. **Not using semantic analysis** - Missing hidden issues
3. **Reviewing too fast** - Missing critical issues
4. **Reviewing too slow** - Blocking team progress
5. **Nitpicking minor issues** - Save for non-blocking comments
6. **Not testing locally** - Missing integration issues
7. **Skipping security review** - Introducing vulnerabilities

## MCP Tools Quick Reference

**Understanding Code**:

- `find_symbol()` - Locate definitions
- `get_type_info()` - Inspect structure
- `get_module_info()` - Module overview

**Impact Analysis**:

- `find_references()` - Find all usages
- `find_subclasses()` - Inheritance impact
- `get_call_hierarchy()` - Execution flow

**Architecture**:

- `analyze_dependencies()` - Module relationships
- `find_imports()` - Who uses this

**Framework-Specific** (Auto-detected):

- `find_routes()` - Flask routes
- `find_django_views()` - Django views
- `find_models()` - Pydantic models

## Success Indicators

✅ **All automated checks pass** - CI green
✅ **Semantic analysis complete** - Used MCP tools effectively
✅ **Standards verified** - PEP compliance, modern Python
✅ **Security reviewed** - No vulnerabilities
✅ **Tests comprehensive** - Good coverage, quality tests
✅ **Architecture sound** - SOLID principles, clean design
✅ **Constructive feedback** - Specific, actionable, kind

## Related Workflows

- [Code Review Standards](workflows://code-review-standards) - Detailed standards checklist
- [Security Review](workflows://code-review-security) - OWASP security guidelines
- [Code Understanding](workflows://code-understanding) - Deep dive into unfamiliar code
- [Refactoring](workflows://refactoring) - Safe refactoring analysis

## Additional Resources

**Code Review Best Practices**:

- [Google Code Review Guidelines](https://google.github.io/eng-practices/review/)
- [Conventional Comments](https://conventionalcomments.org/)
- [Code Review Pyramid](https://www.morling.dev/blog/the-code-review-pyramid/)

**Python Specific**:

- [PEP 8 Style Guide](https://peps.python.org/pep-0008/)
- [Real Python - Code Review](https://realpython.com/python-code-quality/)
- [The Hitchhiker's Guide to Python](https://docs.python-guide.org/writing/style/)
