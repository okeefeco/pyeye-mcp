#!/usr/bin/env python3
"""Prepare a new release by updating versions and creating a release branch."""

import argparse
import re
import subprocess
import sys
from pathlib import Path


def run_command(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        print(f"Error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result


def get_current_version() -> str:
    """Get the current version from pyproject.toml."""
    pyproject = Path("pyproject.toml")
    if not pyproject.exists():
        print("Error: pyproject.toml not found", file=sys.stderr)
        sys.exit(1)

    content = pyproject.read_text()
    match = re.search(r'^version = "(.+?)"', content, re.MULTILINE)
    if not match:
        print("Error: Version not found in pyproject.toml", file=sys.stderr)
        sys.exit(1)

    return match.group(1)


def parse_version(version: str) -> tuple[int, int, int, str]:
    """Parse version string into components."""
    # Remove .dev suffix if present
    base_version = version.replace(".dev0", "")
    parts = base_version.split(".")

    if len(parts) != 3:
        print(f"Error: Invalid version format: {version}", file=sys.stderr)
        sys.exit(1)

    major, minor, patch = map(int, parts)
    dev = ".dev0" if ".dev0" in version else ""

    return major, minor, patch, dev


def update_version(new_version: str) -> None:
    """Update version in all required locations."""
    locations = [
        ("pyproject.toml", r'^version = ".+?"', f'version = "{new_version}"'),
        (
            "pyproject.toml",
            r'^\s*version = ".+?"',
            f'  version = "{new_version}"',
            "[tool.commitizen]",
        ),
        ("src/pycodemcp/__init__.py", r'^__version__ = ".+?"', f'__version__ = "{new_version}"'),
    ]

    for file_path, pattern, replacement, *section in locations:
        path = Path(file_path)
        if not path.exists():
            print(f"Warning: {file_path} not found, skipping", file=sys.stderr)
            continue

        content = path.read_text()

        # If section specified, only replace within that section
        if section:
            section_pattern = re.escape(section[0])
            section_match = re.search(
                f"^{section_pattern}.*?(?=^\\[|\\Z)", content, re.MULTILINE | re.DOTALL
            )
            if section_match:
                section_content = section_match.group(0)
                updated_section = re.sub(pattern, replacement, section_content, flags=re.MULTILINE)
                content = content.replace(section_content, updated_section)
            else:
                print(f"Warning: Section {section[0]} not found in {file_path}", file=sys.stderr)
        else:
            content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

        path.write_text(content)
        print(f"Updated version in {file_path}")


def validate_prerequisites() -> None:
    """Check that all prerequisites are met."""
    # Check git status
    result = run_command(["git", "status", "--porcelain"], check=False)
    if result.stdout.strip():
        print("Error: Working directory is not clean", file=sys.stderr)
        print("Please commit or stash your changes first", file=sys.stderr)
        sys.exit(1)

    # Check current branch
    result = run_command(["git", "branch", "--show-current"])
    current_branch = result.stdout.strip()
    if current_branch != "main":
        print(f"Warning: Not on main branch (current: {current_branch})")
        response = input("Continue anyway? (y/N): ")
        if response.lower() != "y":
            sys.exit(1)

    # Run tests
    print("\nRunning tests...")
    result = run_command(["pytest", "--cov=src/pycodemcp", "--cov-fail-under=85"], check=False)
    if result.returncode != 0:
        print("Error: Tests failed", file=sys.stderr)
        response = input("Continue anyway? (y/N): ")
        if response.lower() != "y":
            sys.exit(1)

    # Check version consistency
    print("\nChecking version consistency...")
    result = run_command(
        ["pytest", "tests/test_version_consistency.py", "-v", "--no-cov"], check=False
    )
    if result.returncode != 0:
        print("Error: Version consistency check failed", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Prepare a new release")
    parser.add_argument("version", nargs="?", help="New version (e.g., 0.2.0)")
    parser.add_argument("--patch", action="store_true", help="Increment patch version")
    parser.add_argument("--minor", action="store_true", help="Increment minor version")
    parser.add_argument("--major", action="store_true", help="Increment major version")
    parser.add_argument(
        "--skip-validation", action="store_true", help="Skip prerequisite validation"
    )
    parser.add_argument("--no-branch", action="store_true", help="Don't create release branch")

    args = parser.parse_args()

    # Get current version
    current_version = get_current_version()
    print(f"Current version: {current_version}")

    # Determine new version
    if args.version:
        new_version = args.version
    else:
        major, minor, patch, dev = parse_version(current_version)

        # Remove .dev0 suffix for release
        if dev:
            new_version = f"{major}.{minor}.{patch}"
        elif args.major:
            new_version = f"{major + 1}.0.0"
        elif args.minor:
            new_version = f"{major}.{minor + 1}.0"
        elif args.patch:
            new_version = f"{major}.{minor}.{patch + 1}"
        else:
            print("Error: No version specified and no increment flag provided", file=sys.stderr)
            print("Use --patch, --minor, --major, or specify a version", file=sys.stderr)
            sys.exit(1)

    print(f"New version: {new_version}")

    # Validate prerequisites
    if not args.skip_validation:
        print("\nValidating prerequisites...")
        validate_prerequisites()

    # Update version
    print(f"\nUpdating version to {new_version}...")
    update_version(new_version)

    # Create release branch
    if not args.no_branch:
        branch_name = f"release/{new_version}"
        print(f"\nCreating release branch: {branch_name}")
        run_command(["git", "checkout", "-b", branch_name])

        # Commit changes
        print("\nCommitting version changes...")
        run_command(["git", "add", "-A"])
        run_command(["git", "commit", "-m", f"chore: prepare release v{new_version}"])

        # Push branch
        print(f"\nPushing branch {branch_name}...")
        run_command(["git", "push", "-u", "origin", branch_name])

        # Create PR
        print("\nCreating pull request...")
        pr_body = f"""Prepare release v{new_version}

## Changes
- Updated version to {new_version}
- See CHANGELOG.md for release notes

## Checklist
- [ ] Tests passing
- [ ] Version consistency verified
- [ ] CHANGELOG.md updated
- [ ] Ready for release
"""
        result = run_command(
            [
                "gh",
                "pr",
                "create",
                "--title",
                f"Release v{new_version}",
                "--body",
                pr_body,
                "--base",
                "main",
            ],
            check=False,
        )

        if result.returncode == 0:
            print("\nPull request created successfully!")
            print(result.stdout)
        else:
            print("\nCouldn't create PR automatically. Please create it manually.")

    print("\n✅ Release preparation complete!")
    print("\nNext steps:")
    print("1. Review and merge the PR")
    print("2. Pull main branch locally")
    print(f"3. Create and push tag: git tag -a v{new_version} -m 'Release v{new_version}'")
    print(f"4. Push tag: git push origin v{new_version}")


if __name__ == "__main__":
    main()
