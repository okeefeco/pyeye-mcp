"""Tests for version validation scripts."""

import subprocess
import sys
from pathlib import Path


class TestIntegration:
    """Integration tests for running scripts on the actual project."""

    def test_current_project_passes(self):
        """Test that the current project passes all validations."""
        project_root = Path(__file__).parent.parent

        # Test check_version.py
        result = subprocess.run(
            [sys.executable, str(project_root / "scripts" / "check_version.py")],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"check_version.py failed: {result.stdout}"

        # Test validate_version_format.py
        result = subprocess.run(
            [sys.executable, str(project_root / "scripts" / "validate_version_format.py")],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"validate_version_format.py failed: {result.stdout}"

        # Test validate_changelog.py
        result = subprocess.run(
            [sys.executable, str(project_root / "scripts" / "validate_changelog.py")],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"validate_changelog.py failed: {result.stdout}"
