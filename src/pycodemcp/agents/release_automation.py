"""Release automation agent for end-to-end release management.

This agent provides natural language interface for automating the complete
release process, eliminating manual execution of 15+ steps.
"""

import re
import subprocess
from pathlib import Path
from typing import Any

from ..exceptions import ValidationError


class ReleaseAutomationAgent:
    """Agent that automates the complete end-to-end release management process."""

    def __init__(self, project_root: Path | None = None):
        """Initialize the release automation agent.

        Args:
            project_root: Root directory of the project. Defaults to current directory.
        """
        self.project_root = project_root or Path.cwd()
        self._ensure_project_root()

    def _ensure_project_root(self) -> None:
        """Validate that we're in a valid project directory."""
        pyproject = self.project_root / "pyproject.toml"
        if not pyproject.exists():
            raise ValidationError(f"No pyproject.toml found in {self.project_root}")

    def handle_request(self, command: str) -> dict[str, Any]:
        """Handle natural language release request.

        Args:
            command: Natural language command like "Prepare release v0.2.0"

        Returns:
            Dictionary with execution results and next steps

        Examples:
            - "Prepare release v0.2.0"
            - "Cut a patch release"
            - "Create release branch for version 0.3.0"
            - "Prepare minor release"
            - "Prepare major release"
        """
        try:
            # Parse the natural language command
            parsed = self._parse_release_command(command)

            # Execute the release workflow
            result = self._execute_release_workflow(parsed)

            return {
                "success": True,
                "command": command,
                "parsed": parsed,
                "result": result,
                "next_steps": self._generate_next_steps(parsed["version"]),
            }

        except Exception as e:
            return {
                "success": False,
                "command": command,
                "error": str(e),
                "error_type": type(e).__name__,
            }

    def _parse_release_command(self, command: str) -> dict[str, Any]:
        """Parse natural language command into structured data.

        Args:
            command: Natural language command

        Returns:
            Dictionary with parsed command details

        Raises:
            ValidationError: If command cannot be parsed
        """
        command = command.lower().strip()

        # Pattern matching for different command types
        patterns = [
            # Specific version: "prepare release v0.2.0", "cut release 0.2.0"
            (r"(?:prepare|cut|create).*?(?:release|version).*?v?(\d+\.\d+\.\d+)", "specific"),
            # Patch release: "cut a patch release", "prepare patch"
            (r"(?:prepare|cut|create).*?patch", "patch"),
            # Minor release: "cut a minor release", "prepare minor"
            (r"(?:prepare|cut|create).*?minor", "minor"),
            # Major release: "cut a major release", "prepare major"
            (r"(?:prepare|cut|create).*?major", "major"),
        ]

        for pattern, release_type in patterns:
            match = re.search(pattern, command)
            if match:
                if release_type == "specific":
                    version = match.group(1)
                    return {"type": "specific", "version": version, "raw_command": command}
                else:
                    return {
                        "type": release_type,
                        "version": None,  # Will be calculated
                        "raw_command": command,
                    }

        # If no pattern matches, try to extract version anyway
        version_match = re.search(r"v?(\d+\.\d+\.\d+)", command)
        if version_match:
            return {"type": "specific", "version": version_match.group(1), "raw_command": command}

        raise ValidationError(
            f"Could not parse release command: '{command}'. "
            "Try commands like 'Prepare release v0.2.0', 'Cut patch release', "
            "'Prepare minor release', or 'Create major release'"
        )

    def _execute_release_workflow(self, parsed: dict[str, Any]) -> dict[str, Any]:
        """Execute the complete release workflow.

        Args:
            parsed: Parsed command details

        Returns:
            Workflow execution results
        """
        # Step 1: Validate prerequisites
        self._validate_prerequisites()

        # Step 2: Determine target version
        target_version = self._determine_target_version(parsed)

        # Step 3: Update version in all locations
        self._update_version(target_version)

        # Step 4: Create release branch and PR
        branch_info = self._create_release_branch(target_version)
        pr_info = self._create_pull_request(target_version, branch_info)

        return {
            "target_version": target_version,
            "branch": branch_info,
            "pull_request": pr_info,
            "files_updated": self._get_version_files(),
        }

    def _validate_prerequisites(self) -> None:
        """Validate all prerequisites for release."""
        # Check git status
        result = self._run_command(["git", "status", "--porcelain"], check=False)
        if result.stdout.strip():
            raise ValidationError(
                "Working directory is not clean. Please commit or stash changes first."
            )

        # Check current branch
        result = self._run_command(["git", "branch", "--show-current"])
        current_branch = result.stdout.strip()
        if current_branch != "main":
            raise ValidationError(
                f"Not on main branch (current: {current_branch}). "
                "Please switch to main branch first."
            )

        # Run tests with coverage
        print("🧪 Running tests with coverage...")
        result = self._run_command(
            ["pytest", "--cov=src/pycodemcp", "--cov-fail-under=85"], check=False
        )
        if result.returncode != 0:
            raise ValidationError(
                "Tests failed or coverage below 85%. Please fix tests before release."
            )

        # Check version consistency
        print("✅ Checking version consistency...")
        result = self._run_command(
            ["pytest", "tests/test_version_consistency.py", "-v", "--no-cov"], check=False
        )
        if result.returncode != 0:
            raise ValidationError("Version consistency check failed.")

        print("✅ All prerequisites validated successfully")

    def _determine_target_version(self, parsed: dict[str, Any]) -> str:
        """Determine the target version for the release.

        Args:
            parsed: Parsed command details

        Returns:
            Target version string
        """
        if parsed["version"]:
            return str(parsed["version"])

        # Get current version and increment appropriately
        current_version = self._get_current_version()
        major, minor, patch, dev = self._parse_version(current_version)

        # Remove .dev0 suffix for release
        if dev:
            return f"{major}.{minor}.{patch}"
        elif parsed["type"] == "major":
            return f"{major + 1}.0.0"
        elif parsed["type"] == "minor":
            return f"{major}.{minor + 1}.0"
        elif parsed["type"] == "patch":
            return f"{major}.{minor}.{patch + 1}"
        else:
            raise ValidationError(f"Unknown release type: {parsed['type']}")

    def _get_current_version(self) -> str:
        """Get the current version from pyproject.toml."""
        pyproject = self.project_root / "pyproject.toml"
        content = pyproject.read_text()
        match = re.search(r'^version = "(.+?)"', content, re.MULTILINE)
        if not match:
            raise ValidationError("Version not found in pyproject.toml")
        return str(match.group(1))

    def _parse_version(self, version: str) -> tuple[int, int, int, str]:
        """Parse version string into components."""
        base_version = version.replace(".dev0", "")
        parts = base_version.split(".")

        if len(parts) != 3:
            raise ValidationError(f"Invalid version format: {version}")

        major, minor, patch = map(int, parts)
        dev = ".dev0" if ".dev0" in version else ""

        return major, minor, patch, dev

    def _update_version(self, new_version: str) -> None:
        """Update version in all required locations."""
        import re
        from collections.abc import Callable
        from re import Match

        def replace_with_indentation(match: Match[str]) -> str:
            """Replace version while preserving original indentation."""
            indentation = match.group(1) if match.groups() else ""
            return f'{indentation}version = "{new_version}"'

        # Process all location updates
        all_locations: list[tuple[str, str, str | Callable[[Match[str]], str], str | None]] = [
            ("pyproject.toml", r'^version = ".+?"', f'version = "{new_version}"', None),
            (
                "pyproject.toml",
                r'^(\s*)version = ".+?"',
                replace_with_indentation,
                "[tool.commitizen]",
            ),
            (
                "src/pycodemcp/__init__.py",
                r'^__version__ = ".+?"',
                f'__version__ = "{new_version}"',
                None,
            ),
        ]

        for file_path, pattern, replacement, section_name in all_locations:
            path = self.project_root / file_path
            if not path.exists():
                print(f"⚠️  Warning: {file_path} not found, skipping")
                continue

            content = path.read_text()

            # If section specified, only replace within that section
            if section_name:
                section_pattern = re.escape(section_name)
                section_match = re.search(
                    f"^{section_pattern}.*?(?=^\\[|\\Z)", content, re.MULTILINE | re.DOTALL
                )
                if section_match:
                    section_content = section_match.group(0)
                    updated_section = re.sub(
                        pattern, replacement, section_content, flags=re.MULTILINE
                    )
                    content = content.replace(section_content, updated_section)
                else:
                    print(f"⚠️  Warning: Section {section_name} not found in {file_path}")
            else:
                content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

            path.write_text(content)
            print(f"✅ Updated version in {file_path}")

    def _create_release_branch(self, version: str) -> dict[str, Any]:
        """Create and push release branch."""
        branch_name = f"release/{version}"

        print(f"🌿 Creating release branch: {branch_name}")
        self._run_command(["git", "checkout", "-b", branch_name])

        print("📝 Committing version changes...")
        self._run_command(["git", "add", "-A"])
        self._run_command(["git", "commit", "-m", f"chore: prepare release v{version}"])

        print(f"🚀 Pushing branch {branch_name}...")
        self._run_command(["git", "push", "-u", "origin", branch_name])

        return {"name": branch_name, "commit_message": f"chore: prepare release v{version}"}

    def _create_pull_request(self, version: str, branch_info: dict[str, Any]) -> dict[str, Any]:
        """Create pull request for the release."""
        print("📋 Creating pull request...")

        pr_body = f"""Prepare release v{version}

## Changes
- Updated version to {version}
- See CHANGELOG.md for release notes

## Checklist
- [x] Tests passing
- [x] Version consistency verified
- [ ] CHANGELOG.md updated
- [ ] Ready for release

🤖 Generated with Release Automation Agent
"""

        result = self._run_command(
            [
                "gh",
                "pr",
                "create",
                "--title",
                f"Release v{version}",
                "--body",
                pr_body,
                "--base",
                "main",
            ],
            check=False,
        )

        if result.returncode == 0:
            pr_url = result.stdout.strip()
            print(f"✅ Pull request created: {pr_url}")
            return {"url": pr_url, "title": f"Release v{version}", "body": pr_body}
        else:
            print("⚠️  Could not create PR automatically")
            return {
                "error": result.stderr,
                "manual_instructions": f"Please create PR manually from branch {branch_info['name']}",
            }

    def _generate_next_steps(self, version: str) -> list[str]:
        """Generate next steps for the user."""
        return [
            "✅ Release preparation complete!",
            "",
            "Next steps:",
            "1. Review and merge the pull request",
            "2. Pull main branch locally after merge",
            f"3. Create and push tag: git tag -a v{version} -m 'Release v{version}'",
            f"4. Push tag: git push origin v{version}",
            "5. GitHub Actions will automatically create the GitHub release",
        ]

    def _get_version_files(self) -> list[str]:
        """Get list of files that contain version information."""
        return ["pyproject.toml", "src/pycodemcp/__init__.py"]

    def _run_command(self, cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
        """Run a command and return the result."""
        print(f"🔧 Running: {' '.join(cmd)}")
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False, cwd=self.project_root
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"Command failed: {result.stderr}")
        return result


def create_release_automation_agent(project_root: Path | None = None) -> ReleaseAutomationAgent:
    """Factory function to create a release automation agent.

    Args:
        project_root: Root directory of the project

    Returns:
        Configured ReleaseAutomationAgent instance
    """
    return ReleaseAutomationAgent(project_root)
