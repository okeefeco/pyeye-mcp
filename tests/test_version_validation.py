"""Tests for version validation scripts."""

import subprocess
import sys
from pathlib import Path


class TestIntegration:
    """Integration tests for running scripts on the actual project."""

    def test_current_project_passes(self):
        """Test that the current project passes all validations."""
        project_root = Path(__file__).parent.parent

        # With setuptools_scm, we only need to validate the changelog
        # The version is automatically managed by git tags

        # Test validate_changelog.py (the only remaining validation script)
        result = subprocess.run(
            [sys.executable, str(project_root / "scripts" / "validate_changelog.py")],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        assert (
            result.returncode == 0
        ), f"validate_changelog.py failed: {result.stdout}\n{result.stderr}"
