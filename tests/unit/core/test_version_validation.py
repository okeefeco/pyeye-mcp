"""Tests for setuptools_scm version management."""

import subprocess
import sys
from pathlib import Path


class TestVersionManagement:
    """Tests for git-based version management with setuptools_scm."""

    def test_version_available(self):
        """Test that version is available from the package."""
        from pyeye import __version__

        assert __version__ is not None
        assert isinstance(__version__, str)
        # Version should be either a clean version (0.3.0) or a dev version (0.3.1.dev0+g...)
        assert "." in __version__

    def test_changelog_validation(self):
        """Test that the changelog follows the expected format."""
        project_root = Path(__file__).parent.parent

        # Validate that changelog.py script works if it exists
        validate_script = project_root / "scripts" / "validate_changelog.py"
        if validate_script.exists():
            result = subprocess.run(
                [sys.executable, str(validate_script)],
                cwd=project_root,
                capture_output=True,
                text=True,
            )
            assert (
                result.returncode == 0
            ), f"validate_changelog.py failed: {result.stdout}\n{result.stderr}"
