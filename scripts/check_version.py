#!/usr/bin/env python3
"""Check version consistency across package files."""

import re
import sys
from pathlib import Path


def get_pyproject_version(pyproject_path: Path) -> str:
    """Extract version from pyproject.toml."""
    # Parse TOML manually to avoid dependency on tomllib/tomli
    content = pyproject_path.read_text()

    # Simple regex to extract version from [project] section
    # This looks for version = "x.y.z" after [project]

    # Find the [project] section
    project_section = re.search(r"\[project\].*?(?=\n\[|\Z)", content, re.DOTALL)
    if not project_section:
        raise ValueError("Could not find [project] section in pyproject.toml")

    # Extract version from the project section
    version_match = re.search(
        r'^version\s*=\s*["\']([^"\']+)["\']', project_section.group(), re.MULTILINE
    )
    if not version_match:
        raise ValueError("Could not find version in [project] section")

    return version_match.group(1)


def get_init_version(init_path: Path) -> str:
    """Extract version from __init__.py."""
    content = init_path.read_text()
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    if not match:
        raise ValueError(f"Could not find __version__ in {init_path}")
    return match.group(1)


def main() -> int:
    """Check version consistency across files."""
    project_root = Path(__file__).parent.parent

    # Check pyproject.toml
    pyproject_path = project_root / "pyproject.toml"
    if not pyproject_path.exists():
        print(f"ERROR: {pyproject_path} not found")
        return 1

    # Check __init__.py
    init_path = project_root / "src" / "pycodemcp" / "__init__.py"
    if not init_path.exists():
        print(f"ERROR: {init_path} not found")
        return 1

    try:
        pyproject_version = get_pyproject_version(pyproject_path)
        print(f"pyproject.toml version: {pyproject_version}")
    except Exception as e:
        print(f"ERROR: Failed to read version from pyproject.toml: {e}")
        return 1

    try:
        init_version = get_init_version(init_path)
        print(f"__init__.py version: {init_version}")
    except Exception as e:
        print(f"ERROR: Failed to read version from __init__.py: {e}")
        return 1

    # Compare versions
    if pyproject_version != init_version:
        print("\n❌ VERSION MISMATCH!")
        print(f"  pyproject.toml: {pyproject_version}")
        print(f"  __init__.py:    {init_version}")
        print("\nVersions must match across all files.")
        return 1

    print(f"\n✅ Version consistency check passed: {pyproject_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
