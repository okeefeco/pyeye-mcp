"""Tests for setuptools_scm version management."""


class TestVersionManagement:
    """Tests for git-based version management with setuptools_scm."""

    def test_version_available(self):
        """Test that version is available from the package."""
        from pyeye import __version__

        assert __version__ is not None
        assert isinstance(__version__, str)
        # Version should be either a clean version (0.3.0) or a dev version (0.3.1.dev0+g...)
        assert "." in __version__
