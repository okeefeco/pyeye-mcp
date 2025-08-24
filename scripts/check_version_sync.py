#!/usr/bin/env python3
"""Check that version numbers are synchronized across all required locations."""

import re
import sys
from pathlib import Path


def get_version_from_pyproject() -> str | None:
    """Get version from pyproject.toml [project] section."""
    pyproject = Path("pyproject.toml")
    if not pyproject.exists():
        return None

    content = pyproject.read_text()
    match = re.search(r'^\[project\].*?^version = "(.+?)"', content, re.MULTILINE | re.DOTALL)
    if match:
        return match.group(1)
    return None


def get_version_from_commitizen() -> str | None:
    """Get version from pyproject.toml [tool.commitizen] section."""
    pyproject = Path("pyproject.toml")
    if not pyproject.exists():
        return None

    content = pyproject.read_text()
    match = re.search(
        r'^\[tool\.commitizen\].*?^\s*version = "(.+?)"', content, re.MULTILINE | re.DOTALL
    )
    if match:
        return match.group(1)
    return None


def get_version_from_init() -> str | None:
    """Get version from __init__.py."""
    init_file = Path("src/pycodemcp/__init__.py")
    if not init_file.exists():
        return None

    content = init_file.read_text()
    match = re.search(r'^__version__ = ["\'](.+?)["\']', content, re.MULTILINE)
    if match:
        return match.group(1)
    return None


def check_versions() -> dict[str, str | None]:
    """Check all version locations and return results."""
    return {
        "pyproject.toml [project]": get_version_from_pyproject(),
        "pyproject.toml [tool.commitizen]": get_version_from_commitizen(),
        "src/pycodemcp/__init__.py": get_version_from_init(),
    }


def main() -> int:
    """Main entry point."""
    print("Checking version synchronization...\n")

    versions = check_versions()

    # Display results
    print("Version locations:")
    print("-" * 60)
    for location, version in versions.items():
        status = "✅" if version else "❌"
        version_str = version if version else "NOT FOUND"
        print(f"{status} {location:40} {version_str}")

    print("-" * 60)

    # Check if all versions exist
    missing = [loc for loc, ver in versions.items() if ver is None]
    if missing:
        print("\n❌ Missing versions in:")
        for loc in missing:
            print(f"  - {loc}")
        sys.exit(1)

    # Check if all versions match
    unique_versions = {v for v in versions.values() if v is not None}
    if len(unique_versions) > 1:
        print("\n❌ Version mismatch detected!")
        print(f"Found versions: {', '.join(sorted(unique_versions))}")
        print("\nVersions should be synchronized across all locations.")
        sys.exit(1)

    # Success
    version = list(unique_versions)[0]
    print(f"\n✅ All versions synchronized: {version}")

    # Check for dev version
    if ".dev" in version:
        print("⚠️  Note: This is a development version")
        print("   Remove '.dev0' suffix when creating a release")

    return 0


if __name__ == "__main__":
    sys.exit(main())
