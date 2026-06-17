# Complete Pull Request Review Workflow

## Goal

Perform comprehensive pull request reviews combining automated checks, semantic analysis, code standards, and security review. This workflow ensures code quality, safety, and maintainability before merging to main.

> Tool mechanics (call signatures, return shapes, the supported edge set, and the honest
> limits on reverse-reference data) live in the python-explore skill:
> `skills/python-explore/SKILL.md`. This playbook names the tools to use at each step;
> consult the skill for how to call them.

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

## Steps

This workflow consists of 8 phases (see detailed process below):

1. **Automated Analysis** - Verify CI passes (5 min)
2. **PR Context Understanding** - Read PR and understand changes (10 min)
3. **Semantic Impact Analysis** - Use MCP tools to analyze impact (15 min)
4. **Code Standards Review** - Check PEP compliance, quality metrics, and best practices (15 min)
5. **Security Review** - OWASP security checklist (15 min)
6. **Testing Review** - Verify test quality and coverage (10 min)
7. **Architecture & Design Review** - Check SOLID principles (15 min)
8. **Manual Code Review** - Review logic, readability, performance (20 min)

**Total time**: 20-25 minutes (small PR), 35-50 minutes (medium PR), 1-2 hours (large PR)

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

- For each major changed module, `outline` it for its skeleton (exports, top-level defs)
  and `inspect` individual symbols for signature and `edge_counts`.
- Run `analyze_dependencies` on the module to see its import relationships and any
  circular dependencies.

### Phase 3: Semantic Impact Analysis (15 minutes)

**For Each Significant Change**:

> **Honest limit on impact analysis.** pyeye cannot reliably answer "who calls this?"
> or "what references this?" yet — reverse-reference edges are deferred to the Pyright
> backend ([#333](https://github.com/okeefeco/pyeye-mcp/issues/333)), and an anchored
> reverse search under-reports non-deterministically. Do **not** fake call-site or
> usage coverage with grep or legacy tools. State the limit and lean on the forward
> edges pyeye *can* answer: `callees`, `imported_by`, `subclasses`, `superclasses`,
> `imports`, `members`.

#### If New Class Added

- `resolve` the class to its canonical handle, then `inspect` it for kind, signature,
  docstring, and `edge_counts` (documentation, structure, patterns).
- `expand` the `superclasses` edge to confirm it sits sensibly in the inheritance tree,
  and `expand` `subclasses` to see what (if anything) already extends it.
- You cannot statically enumerate every usage of the new class (deferred, #333). If the
  class lands in a module others import, `expand` that module's `imported_by` edge to
  see which modules now reach it.

#### If Function Modified

- `resolve` the function, then `inspect` it to confirm its signature and surrounding
  structure.
- Reliable caller enumeration is not available (deferred, #333) — say so rather than
  guessing. Forward, you can `expand` the function's `callees` edge (or `trace` along
  `callees` for the multi-hop call structure) to confirm its own calls still make sense.
- For breaking signature changes, treat caller impact as **unverified by pyeye** and
  confirm callers are updated by reading the diff and the PR's own changes.

#### If Refactoring/Rename

- Use the Refactoring Workflow (`workflows://refactoring`).
- pyeye cannot give you the full "all usages updated?" answer (deferred, #333). Verify
  renamed references from the diff itself; do not substitute grep as if it were complete.
- If a class, `expand` its `subclasses` edge to confirm subclasses still resolve.
- Run `analyze_dependencies` on the refactored module to catch broken or shifted imports.

### Phase 4: Code Standards Review (10 minutes)

**Use Standards Workflow**: [workflows://code-review-standards](workflows://code-review-standards)

**Key Checks**:

- [ ] Naming follows PEP 8 conventions
- [ ] Type hints complete and modern (Python 3.9+ syntax)
- [ ] Docstrings follow PEP 257
- [ ] Modern Python features used (3.10+)
- [ ] No anti-patterns (mutable defaults, god functions, etc.)
- [ ] Tests are independent and comprehensive

**Code Quality Metrics** (on changed files only):

```bash
# Get list of changed Python files
git diff main...HEAD --name-only | grep '\.py$' > changed_files.txt

# Check complexity
ruff check --select C90 $(cat changed_files.txt)

# Check magic values
ruff check --select PLR2004 $(cat changed_files.txt)

# Check function parameters
ruff check --select PLR0913 $(cat changed_files.txt)

# Check too many branches/returns/statements
ruff check --select PLR0911,PLR0912,PLR0915 $(cat changed_files.txt)
```

**Quality Standards**:

- [ ] Cyclomatic complexity ≤10 per function
- [ ] No magic strings or numbers (use constants)
- [ ] Functions have ≤5 parameters
- [ ] Functions are ≤50 lines (excluding docstrings)

**Note**: If changed files have existing violations, don't require fixing them in this PR. Create a follow-up issue instead.

**Quick MCP Checks**:

- `outline` the new module to review whether its exports follow naming conventions.
- `inspect` individual symbols to verify type hints are present and signatures are correct.

### Phase 5: Security Review (15 minutes)

**Use Security Workflow**: [workflows://code-review-security](workflows://code-review-security)

**Critical Security Checks**:

- [ ] Input validation on all user data
- [ ] No SQL/command injection vulnerabilities
- [ ] Passwords properly hashed
- [ ] No hardcoded secrets
- [ ] Dependencies scanned (pip-audit, safety)

**For High-Risk Changes**:

- Trace forward data flow from an input handler by `expand`-ing its `callees` edge (or
  `trace` along `callees`) to confirm input is validated and output sanitized along the
  path it actually calls.
- `resolve` and `inspect` the auth helpers the change touches. Note that pyeye cannot
  enumerate every protected resource that calls into auth (reverse references deferred,
  #333) — verify auth coverage from the diff and the endpoints under review, not from a
  fabricated caller list.

### Phase 6: Testing Review (10 minutes)

**Test Quality Checks**:

- [ ] New code has tests (90%+ coverage)
- [ ] Bug fixes have regression tests
- [ ] Tests are independent (no shared state)
- [ ] Performance tests use proper thresholds
- [ ] Edge cases covered

**MCP Tool - Test Coverage**:

- pyeye cannot reliably list which tests reference the new code (reverse references
  deferred, #333) — confirm test presence from the PR's added test files rather than a
  reverse lookup.
- For a given test, `resolve` it and `expand` its `callees` edge (or `trace` along
  `callees`) to verify it actually exercises the main code paths.

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

- Run `analyze_dependencies` on the new module; its `circular_dependencies` should be
  empty.
- `expand` the core module's `imported_by` edge to verify only appropriate modules
  import it, and its `imports` edge to check what it depends on.
- `expand` a base class's `subclasses` edge to review the inheritance hierarchy — make
  sure it makes sense and is not too deep.

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

```text
# Understand new endpoint — resolve then inspect
resolve("api.users.get_user_profile")  → handle at api/users.py:67
inspect(handle)
  → Function: get_user_profile(user_id: int) -> ProfileResponse
  → Docstring: Complete ✅
  → Type hints: Present ✅

# Forward call flow — expand the callees edge
expand(handle, edge="callees")
  → Calls: get_user, check_privacy_settings, format_profile ✅
  (Who calls this endpoint isn't statically available — deferred, #333 —
   but for a route the caller is the framework router by construction.)

# Verify model structure — outline the module
outline("models.profile")
  → Exports: ProfileModel, PrivacySettings ✅
expand("models.profile", edge="imports")
  → Imports: pydantic, enum ✅

# Model usage: pyeye can't enumerate every reference (deferred, #333).
# Forward instead — which modules import the model's module:
expand("models.profile", edge="imported_by")
  → api.users, serializers ✅ (test usage confirmed from the PR's test files)
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

```text
# Check authorization — resolve + inspect the endpoint
resolve("api.users.get_user_profile") → handle
inspect(handle) → Has @require_auth decorator ✅

# Forward data flow for user_id — expand callees
expand(handle, edge="callees")
  → user_id validated as int (FastAPI) ✅
  → No SQL injection risk (ORM used) ✅

# Check privacy logic (reached via callees)
  → check_privacy_settings() verifies access ✅
  → Returns 403 if unauthorized ✅

# No secrets in code
  → detect-secrets passed ✅
```

### 6. Testing Review (5 min)

```text
# pyeye can't reverse-map endpoint → tests (deferred, #333).
# Confirm the tests from the PR's added test file:
  → test_get_user_profile_success ✅
  → test_get_user_profile_not_found ✅
  → test_get_user_profile_unauthorized ✅
  → test_get_user_profile_privacy ✅

# Verify each test exercises the endpoint — expand its callees
expand("tests.test_users_api.test_get_user_profile_success", edge="callees")
  → calls get_user_profile ✅

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

- [ ] Used `resolve` + `inspect` (or `outline`) to orient on changed symbols
- [ ] Used `expand(edge="callees")` / `trace` to understand forward call flow
- [ ] Used `analyze_dependencies` for module changes
- [ ] Used `expand(edge="subclasses")` for class changes
- [ ] Stated honestly where caller/reference impact is unverified (deferred, #333)

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

See `skills/python-explore/SKILL.md` for call signatures, the full supported-edge set,
and the honest limits.

**Understanding Code**:

- `resolve` - Name/position → canonical handle
- `inspect` - Structure, signature, docstring, `edge_counts`
- `outline` - Module/class skeleton in one call

**Impact Analysis** (forward edges only — reverse references deferred, #333):

- `expand(edge="callees")` / `trace` - Forward call flow
- `expand(edge="subclasses")` / `expand(edge="superclasses")` - Inheritance
- `expand(edge="imported_by")` / `expand(edge="imports")` - Module usage and deps

**Not available yet**: reliable "who calls / what references this" (deferred to the
Pyright backend, #333). State the limit; do not fake it.

**Architecture**:

- `analyze_dependencies` - Module relationships and circular deps

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
