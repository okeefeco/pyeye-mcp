"""Tests for version consistency across package files.

This module ensures that version information is synchronized between:
- pyproject.toml
- src/pycodemcp/__init__.py

This prevents version drift during releases and ensures all package metadata
references the same version.
"""

import re
from pathlib import Path

import tomllib


def test_version_consistency():
    """Test that __version__ in __init__.py matches version in pyproject.toml."""
    # Get paths relative to the test file
    test_dir = Path(__file__).parent
    repo_root = test_dir.parent

    # Read version from pyproject.toml
    pyproject_path = repo_root / "pyproject.toml"
    assert pyproject_path.exists(), f"pyproject.toml not found at {pyproject_path}"

    with open(pyproject_path, "rb") as f:
        pyproject_data = tomllib.load(f)

    pyproject_version = pyproject_data["project"]["version"]
    assert pyproject_version, "No version found in pyproject.toml"

    # Read version from __init__.py
    init_py_path = repo_root / "src" / "pycodemcp" / "__init__.py"
    assert init_py_path.exists(), f"__init__.py not found at {init_py_path}"

    with open(init_py_path, encoding="utf-8") as f:
        init_py_content = f.read()

    # Extract __version__ using regex to handle different quote styles
    version_pattern = r'__version__\s*=\s*["\']([^"\']+)["\']'
    version_match = re.search(version_pattern, init_py_content)
    assert version_match, "No __version__ found in __init__.py"

    init_py_version = version_match.group(1)

    # Versions must match
    assert pyproject_version == init_py_version, (
        f"Version mismatch: pyproject.toml has '{pyproject_version}' "
        f"but __init__.py has '{init_py_version}'"
    )


def test_version_import():
    """Test that __version__ can be imported successfully."""
    # Test the import works (this also validates the __init__.py structure)
    from pycodemcp import __version__

    # Should be a non-empty string
    assert isinstance(__version__, str)
    assert len(__version__.strip()) > 0

    # Should follow semantic versioning pattern (basic check)
    # Supports: X.Y.Z, X.Y.Z.devN, X.Y.ZaN, X.Y.ZbN, X.Y.ZrcN
    version_pattern = r"^\d+\.\d+\.\d+(\.(dev|a|b|rc)\d+|\w.*)?$"
    assert re.match(
        version_pattern, __version__
    ), f"Version '{__version__}' doesn't follow semantic versioning pattern"


def test_commitizen_version_files():
    """Test that commitizen is configured to update both version files."""
    # Get paths relative to the test file
    test_dir = Path(__file__).parent
    repo_root = test_dir.parent

    # Read commitizen config from pyproject.toml
    pyproject_path = repo_root / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        pyproject_data = tomllib.load(f)

    commitizen_config = pyproject_data.get("tool", {}).get("commitizen", {})
    version_files = commitizen_config.get("version_files", [])

    # Should contain both files
    expected_files = ["pyproject.toml:version", "src/pycodemcp/__init__.py:__version__"]

    for expected_file in expected_files:
        assert expected_file in version_files, (
            f"Missing '{expected_file}' from commitizen version_files config. "
            f"Found: {version_files}"
        )
