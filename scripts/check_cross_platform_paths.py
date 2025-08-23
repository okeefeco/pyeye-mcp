#!/usr/bin/env python3
"""Pre-commit hook to check for cross-platform path handling violations.

This script looks for common patterns that violate our cross-platform path guidelines:
1. Using str(Path) for display/storage instead of .as_posix()
2. String interpolation with Path objects without .as_posix()
3. Dictionary keys using str(Path) instead of path_to_key()

Exit codes:
0 - No violations found
1 - Violations found
"""

import ast
import sys
from pathlib import Path


class PathViolationChecker(ast.NodeVisitor):
    """AST visitor to find cross-platform path violations."""

    def __init__(self, filename: str, source_lines: list[str]):
        """Initialize the checker with a filename and source lines."""
        self.filename = filename
        self.source_lines = source_lines
        self.violations: list[tuple[int, str]] = []

    def _is_suppressed(self, line_no: int) -> bool:
        """Check if a line has a suppression comment."""
        if 0 <= line_no - 1 < len(self.source_lines):
            line = self.source_lines[line_no - 1]
            return "# noqa: path-check" in line or "# path-check: ignore" in line
        return False

    def visit_Call(self, node: ast.Call) -> None:
        """Check function calls for str(Path) usage."""
        # Skip if line is suppressed
        if self._is_suppressed(node.lineno):
            return

        # Check for str(path_like_variable)
        if isinstance(node.func, ast.Name) and node.func.id == "str" and len(node.args) == 1:
            arg = node.args[0]

            # Look for variables that might be Path objects
            if isinstance(arg, ast.Name) and self._looks_like_path_variable(arg.id):
                self.violations.append(
                    (
                        node.lineno,
                        f"Use of str({arg.id}) detected. Consider {arg.id}.as_posix() for display/storage",
                    )
                )

            # Look for Path() constructor calls
            elif (
                isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Name)
                and arg.func.id == "Path"
            ):
                self.violations.append(
                    (
                        node.lineno,
                        "Use of str(Path(...)) detected. Consider Path(...).as_posix() for display/storage",
                    )
                )

        self.generic_visit(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        """Check f-strings for Path objects without .as_posix()."""
        # Skip if line is suppressed
        if self._is_suppressed(node.lineno):
            return

        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                if isinstance(value.value, ast.Name) and self._looks_like_path_variable(
                    value.value.id
                ):
                    self.violations.append(
                        (
                            node.lineno,
                            f"f-string with {value.value.id} detected. Consider {{path.as_posix()}} for display",
                        )
                    )

        self.generic_visit(node)

    def _looks_like_path_variable(self, name: str) -> bool:
        """Heuristic to identify variables that might be Path objects."""
        # Exclude common false positives
        false_positives = [
            "module_path",  # Python module path (e.g., "os.path")
            "import_path",  # Import path
            "xpath",  # XML path
            "jsonpath",  # JSON path
            "classpath",  # Java classpath
            "pythonpath",  # Python module search path
            "sys_path",  # sys.path
        ]

        name_lower = name.lower()

        # Check if it's a known false positive
        if any(fp in name_lower for fp in false_positives):
            return False

        # Check for path indicators
        path_indicators = [
            "path",
            "file",
            "dir",
            "directory",
            "folder",
            "location",
            "template_file",
            "config_file",
            "source_file",
            "target_file",
        ]

        return any(indicator in name_lower for indicator in path_indicators)


def check_file_for_violations(filepath: Path) -> list[tuple[int, str]]:
    """Check a Python file for cross-platform path violations."""
    try:
        content = filepath.read_text(encoding="utf-8")
        lines = content.splitlines()

        # Skip files that import path_utils (they're probably doing it right)
        if (
            "from pycodemcp.path_utils import" in content
            or "import pycodemcp.path_utils" in content
        ):
            return []

        # Parse the AST
        tree = ast.parse(content, filename=str(filepath))

        # Check for violations
        checker = PathViolationChecker(str(filepath), lines)
        checker.visit(tree)

        return checker.violations

    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"Warning: Could not parse {filepath}: {e}")
        return []


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: check_cross_platform_paths.py <file1> [file2] ...")
        return 1

    all_violations = []

    for filepath in sys.argv[1:]:
        path = Path(filepath)
        if not path.exists() or path.suffix != ".py":
            continue

        violations = check_file_for_violations(path)

        for line_no, message in violations:
            all_violations.append((filepath, line_no, message))

    if all_violations:
        print("❌ Cross-platform path violations found:")
        print()

        for filepath, line_no, message in all_violations:
            print(f"  {filepath}:{line_no}: {message}")

        print()
        print("💡 Fix suggestions:")
        print("  - For display/storage: use path.as_posix() instead of str(path)")
        print("  - For dictionary keys: use path_to_key(path) from pycodemcp.path_utils")
        print("  - For comparisons: use paths_equal(p1, p2) from pycodemcp.path_utils")
        print("  - See CONTRIBUTING.md 'Cross-Platform Development' section for details")

        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
