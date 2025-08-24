#!/usr/bin/env python3
"""Validate version format follows semantic versioning."""

import re
import sys
from pathlib import Path
from typing import Any

import tomllib

# Semantic versioning pattern with optional pre-release and build metadata
# Matches: X.Y.Z, X.Y.Z.devN, X.Y.Z.alphaN, X.Y.Z.betaN, X.Y.Z.rcN, X.Y.Z+build
SEMVER_PATTERN = re.compile(
    r"^"
    r"(0|[1-9]\d*)\."  # Major version
    r"(0|[1-9]\d*)\."  # Minor version
    r"(0|[1-9]\d*)"  # Patch version
    r"(?:\.(dev|alpha|beta|rc)(\d+))?"  # Optional pre-release (Python-style)
    r"(?:\+[0-9a-zA-Z\-\.]+)?"  # Optional build metadata
    r"$"
)

# PEP 440 compatible pattern (more permissive for Python packages)
PEP440_PATTERN = re.compile(
    r"^"
    r"(0|[1-9]\d*)"  # Major
    r"(?:\.(0|[1-9]\d*))?"  # Optional minor
    r"(?:\.(0|[1-9]\d*))?"  # Optional patch
    r"(?:"  # Optional pre-release
    r"(?:a|alpha|b|beta|rc|dev)"
    r"(?:\d+)?"
    r")?"
    r"(?:\+[0-9a-zA-Z\-\.]+)?"  # Optional local version
    r"$"
)


def get_current_version(pyproject_path: Path) -> str:
    """Extract version from pyproject.toml."""
    with open(pyproject_path, "rb") as f:
        data: dict[str, Any] = tomllib.load(f)
    return str(data["project"]["version"])


def validate_semver(version: str) -> tuple[bool, str]:
    """Validate version against semantic versioning."""
    if SEMVER_PATTERN.match(version):
        return True, "Valid semantic version"
    return False, "Does not match semantic versioning pattern (X.Y.Z)"


def validate_pep440(version: str) -> tuple[bool, str]:
    """Validate version against PEP 440."""
    if PEP440_PATTERN.match(version):
        return True, "Valid PEP 440 version"
    return False, "Does not match PEP 440 pattern"


def parse_version_components(version: str) -> dict[str, Any]:
    """Parse version into components."""
    match = SEMVER_PATTERN.match(version)
    if not match:
        return {}

    components: dict[str, Any] = {
        "major": int(match.group(1)),
        "minor": int(match.group(2)),
        "patch": int(match.group(3)),
        "prerelease": None,
        "prerelease_num": None,
    }

    if match.group(4):  # Pre-release type (dev, alpha, beta, rc)
        components["prerelease"] = match.group(4)
        if match.group(5):  # Pre-release number
            components["prerelease_num"] = int(match.group(5))

    return components


def main() -> int:
    """Validate version format."""
    project_root = Path(__file__).parent.parent

    # Check pyproject.toml exists
    pyproject_path = project_root / "pyproject.toml"
    if not pyproject_path.exists():
        print(f"ERROR: {pyproject_path} not found")
        return 1

    try:
        current_version = get_current_version(pyproject_path)
        print(f"Validating version: {current_version}")
    except Exception as e:
        print(f"ERROR: Failed to read version from pyproject.toml: {e}")
        return 1

    # Validate against semantic versioning
    semver_valid, semver_msg = validate_semver(current_version)
    print(f"  Semantic versioning: {'✅' if semver_valid else '❌'} {semver_msg}")

    # Validate against PEP 440 (Python standard)
    pep440_valid, pep440_msg = validate_pep440(current_version)
    print(f"  PEP 440 compliance: {'✅' if pep440_valid else '❌'} {pep440_msg}")

    # Parse components if valid
    if semver_valid:
        components = parse_version_components(current_version)
        if components:
            print("\nVersion components:")
            print(f"  Major: {components['major']}")
            print(f"  Minor: {components['minor']}")
            print(f"  Patch: {components['patch']}")
            if components["prerelease"]:
                print(f"  Pre-release: {components['prerelease']}")
                if components["prerelease_num"] is not None:
                    print(f"  Pre-release number: {components['prerelease_num']}")

    # Require at least semantic versioning compliance
    if not semver_valid:
        print("\n❌ VERSION FORMAT VALIDATION FAILED!")
        print(f"  Version '{current_version}' does not follow semantic versioning")
        print("\nExpected format: X.Y.Z or X.Y.Z.devN or X.Y.Z.alphaN etc.")
        print("Examples: 1.0.0, 0.2.1, 1.0.0.dev0, 2.1.0.beta1, 3.0.0.rc2")
        return 1

    # Warnings for best practices
    if semver_valid:
        components = parse_version_components(current_version)

        # Warn about 0.0.0
        if components and all(components[k] == 0 for k in ["major", "minor", "patch"]):
            print("\n⚠️  WARNING: Version 0.0.0 is not recommended for releases")

        # Suggest using dev versions for unreleased code
        if components and components["major"] == 0 and not components["prerelease"]:
            print("\n⚠️  NOTE: Consider using 0.x.y.dev0 for development versions")

    print("\n✅ Version format validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
