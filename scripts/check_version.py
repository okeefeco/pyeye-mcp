#!/usr/bin/env python3
"""Check version consistency across package files."""

import re
import sys
from pathlib import Path
from typing import Any

import tomllib


def get_pyproject_version(pyproject_path: Path) -> str:
    """Extract version from pyproject.toml."""
    with open(pyproject_path, "rb") as f:
        data: dict[str, Any] = tomllib.load(f)
    return str(data["project"]["version"])


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
