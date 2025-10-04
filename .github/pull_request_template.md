## Description
<!-- Provide a brief description of the changes -->

## Related Issue
<!-- Link to the issue this PR addresses -->
Fixes #

## Type of Change
<!-- Mark the relevant option with an "x" -->
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Performance improvement
- [ ] Code refactoring

## Checklist
<!-- Mark completed items with an "x" -->
- [ ] My code follows the project's style guidelines
- [ ] I have performed a self-review of my own code
- [ ] I have added/updated documentation as needed
- [ ] I have added tests that prove my fix is effective or that my feature works
- [ ] New and existing unit tests pass locally with my changes
- [ ] I have run pre-commit hooks successfully
- [ ] I have checked for security vulnerabilities

## Coverage Requirements
<!-- IMPORTANT: We're working towards 85% coverage. Every PR must maintain or improve coverage -->
- [ ] Coverage maintained or improved from baseline (run `pytest --cov=src/pyeye --cov-report=term`)
- [ ] New code has >90% coverage
- [ ] Files with <75% coverage have been improved (if modified)
- [ ] No significant coverage drops in modified files

## Code Quality Metrics
<!-- Check quality metrics on changed files only -->
<!-- See src/pyeye/workflows/code_review_standards.md for details -->

### Complexity & Maintainability

- [ ] No functions with cyclomatic complexity >10 (run `ruff check --select C90 <changed_files>`)
- [ ] No functions with >5 parameters (run `ruff check --select PLR0913 <changed_files>`)
- [ ] No functions longer than 50 lines (excluding docstrings)
- [ ] No excessive branching (run `ruff check --select PLR0912 <changed_files>`)

### Code Clarity

- [ ] No magic numbers or strings - use named constants (run `ruff check --select PLR2004 <changed_files>`)
- [ ] No code duplication (check for similar blocks manually or with pylint)
- [ ] Clear variable and function names
- [ ] Appropriate abstractions used

### Note on Existing Violations

If your changes touch existing code with quality violations, you don't need to fix them in this PR. However, consider creating a follow-up issue to address them.

## Testing
<!-- Describe the tests you ran to verify your changes -->

## Screenshots (if applicable)
<!-- Add screenshots to help explain your changes -->

## Additional Notes
<!-- Add any additional notes or context about the PR -->
