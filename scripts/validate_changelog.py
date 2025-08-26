#!/usr/bin/env python3
"""Validate changelog entries for current version."""

import re
import sys
from pathlib import Path


def get_current_version(pyproject_path: Path) -> str:  # noqa: ARG001
    """Extract version from git tags via setuptools_scm.

    Args:
        pyproject_path: Path to pyproject.toml (kept for compatibility, not used)
    """
    try:
        # Try setuptools_scm first
        from setuptools_scm import get_version

        version = get_version(root=pyproject_path.parent)
        # For development versions, extract base version
        # e.g., "0.2.1.dev0+g123456" -> "0.2.1"
        base_version: str = version.split(".dev")[0].split("+")[0]
        return base_version
    except (ImportError, Exception):
        # Fall back to git describe
        import subprocess

        try:
            result = subprocess.run(
                ["git", "describe", "--tags", "--match", "v*"],
                capture_output=True,
                text=True,
                check=True,
            )
            version = result.stdout.strip()
            # Remove 'v' prefix if present
            if version.startswith("v"):
                version = version[1:]
            # For development versions, extract base version
            if "-" in version:
                version = version.split("-")[0]
            return version
        except subprocess.CalledProcessError:
            # No tags found, return a default
            return "0.2.0"  # Return the last known version instead of 0.0.0


def parse_changelog(changelog_path: Path) -> dict:
    """Parse changelog and extract version entries."""
    content = changelog_path.read_text()

    # Pattern for version headers like ## [0.1.0] - 2024-01-01 or ## 0.1.0 - 2024-01-01
    version_pattern = r"^##\s+\[?([0-9]+\.[0-9]+\.[0-9]+(?:\.[a-z0-9]+)?)\]?\s*(?:-\s*(.+))?$"

    versions = {}
    current_version = None
    current_content: list[str] = []

    for line in content.split("\n"):
        match = re.match(version_pattern, line, re.IGNORECASE)
        if match:
            # Save previous version content
            if current_version:
                versions[current_version] = {
                    "date": versions[current_version].get("date"),
                    "content": "\n".join(current_content).strip(),
                }

            # Start new version
            current_version = match.group(1)
            date_str = match.group(2) if match.group(2) else None
            versions[current_version] = {"date": date_str, "content": ""}
            current_content = []
        elif current_version:
            current_content.append(line)

    # Save last version content
    if current_version:
        versions[current_version] = {
            "date": versions[current_version].get("date"),
            "content": "\n".join(current_content).strip(),
        }

    return versions


def validate_unreleased_section(changelog_content: str) -> bool:
    """Check if there's an Unreleased section for development versions."""
    return bool(
        re.search(r"^##\s+\[?Unreleased\]?", changelog_content, re.MULTILINE | re.IGNORECASE)
    )


def main() -> int:
    """Validate changelog entries."""
    project_root = Path(__file__).parent.parent

    # Check files exist
    pyproject_path = project_root / "pyproject.toml"
    changelog_path = project_root / "CHANGELOG.md"

    if not pyproject_path.exists():
        print(f"ERROR: {pyproject_path} not found")
        return 1

    if not changelog_path.exists():
        print(f"ERROR: {changelog_path} not found")
        return 1

    try:
        current_version = get_current_version(pyproject_path)
        print(f"Current version: {current_version}")
    except Exception as e:
        print(f"ERROR: Failed to read version from pyproject.toml: {e}")
        return 1

    try:
        changelog_content = changelog_path.read_text()
        versions = parse_changelog(changelog_path)
        print(f"Found {len(versions)} version entries in changelog")
    except Exception as e:
        print(f"ERROR: Failed to parse changelog: {e}")
        return 1

    # Check if version is a development version by looking at the actual git state
    import subprocess

    try:
        # Check if there are commits after the last tag
        result = subprocess.run(
            ["git", "describe", "--tags", "--match", "v*"],
            capture_output=True,
            text=True,
            check=False,
        )
        is_dev_version = "-" in result.stdout if result.returncode == 0 else True
    except Exception:
        is_dev_version = True  # Assume dev if we can't determine

    # Also check version string patterns
    is_dev_version = is_dev_version or any(
        marker in current_version for marker in ["dev", "alpha", "beta", "rc", "+"]
    )

    if is_dev_version:
        # For development versions, check if base version has a changelog entry
        # This is more lenient - we just warn about missing Unreleased section
        base_version = current_version.split(".dev")[0].split("+")[0].split("-")[0]

        if base_version in versions:
            print(f"[PASS] Found changelog entry for base version {base_version}")
        elif not validate_unreleased_section(changelog_content):
            print(
                f"\n[WARNING] Development version (based on {base_version}) but no 'Unreleased' section in changelog"
            )
            print("Consider adding an 'Unreleased' section for ongoing development")
        else:
            print("[PASS] Found 'Unreleased' section for development version")
    else:
        # Release versions must have a changelog entry
        if current_version not in versions:
            print("\n[ERROR] CHANGELOG VALIDATION FAILED!")
            print(f"  Version {current_version} not found in CHANGELOG.md")
            print(f"  Found versions: {', '.join(sorted(versions.keys(), reverse=True)[:5])}")
            print("\nPlease add a changelog entry for the current version.")
            return 1

        version_info = versions[current_version]

        # Check if entry has content
        if not version_info["content"] or len(version_info["content"].strip()) < 10:
            print("\n[ERROR] CHANGELOG VALIDATION FAILED!")
            print(f"  Version {current_version} has no meaningful content in changelog")
            print("\nPlease add details about what changed in this version.")
            return 1

        # Check if entry has a date (warning only)
        if not version_info["date"]:
            print(f"\n[WARNING] Version {current_version} has no date in changelog")
            print("Consider adding a date in format: ## [x.y.z] - YYYY-MM-DD")

        print(f"\n[PASS] Changelog validation passed for version {current_version}")
        if version_info["date"]:
            print(f"  Date: {version_info['date']}")
        print(f"  Content length: {len(version_info['content'])} characters")

    return 0


if __name__ == "__main__":
    sys.exit(main())
