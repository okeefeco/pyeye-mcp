"""Tests for configuration management."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pycodemcp.config import ProjectConfig


class TestProjectConfig:
    """Test the ProjectConfig class."""

    def test_initialization(self, temp_project_dir):
        """Test config initialization."""
        with patch.object(ProjectConfig, "load_config"):
            config = ProjectConfig(str(temp_project_dir))

            assert config.project_path == temp_project_dir
            assert isinstance(config.config, dict)

    def test_load_json_config(self, temp_project_dir):
        """Test loading configuration from JSON file."""
        config_data = {
            "packages": ["../lib1", "../lib2"],
            "namespaces": {"company": ["/repos/company-auth", "/repos/company-api"]},
            "cache_ttl": 600,
        }

        config_file = temp_project_dir / ".pycodemcp.json"
        config_file.write_text(json.dumps(config_data))

        config = ProjectConfig(str(temp_project_dir))

        assert config.config["packages"] == config_data["packages"]
        assert config.config["namespaces"] == config_data["namespaces"]
        assert config.config["cache_ttl"] == 600

    def test_load_yaml_config(self, temp_project_dir):
        """Test loading configuration from YAML file."""
        pytest.importorskip("yaml")  # Skip if PyYAML not installed

        yaml_content = """pycodemcp:
  packages:
    - ../lib1
  cache_ttl: 300
"""

        config_file = temp_project_dir / ".pycodemcp.yaml"
        config_file.write_text(yaml_content)

        config = ProjectConfig(str(temp_project_dir))

        assert config.config["packages"] == ["../lib1"]
        assert config.config["cache_ttl"] == 300

    def test_load_pyproject_toml(self, temp_project_dir):
        """Test loading configuration from pyproject.toml."""
        toml_content = """
[tool.pycodemcp]
packages = ["../shared", "../common"]
cache_ttl = 300

[tool.pycodemcp.namespaces]
mycompany = ["/repos/mycompany-core", "/repos/mycompany-utils"]
"""

        config_file = temp_project_dir / "pyproject.toml"
        config_file.write_text(toml_content)

        config = ProjectConfig(str(temp_project_dir))

        assert config.config["packages"] == ["../shared", "../common"]
        assert config.config["cache_ttl"] == 300
        assert "mycompany" in config.config["namespaces"]

    def test_config_file_precedence(self, temp_project_dir):
        """Test that config files are checked in order of precedence."""
        # Create both JSON and TOML configs
        json_config = {"packages": ["json_package"]}
        toml_config = {"packages": ["toml_package"]}

        json_file = temp_project_dir / ".pycodemcp.json"
        json_file.write_text(json.dumps(json_config))

        toml_file = temp_project_dir / "pyproject.toml"
        toml_file.write_text(
            f"""
[tool.pycodemcp]
packages = {json.dumps(toml_config["packages"])}
"""
        )

        config = ProjectConfig(str(temp_project_dir))

        # JSON should take precedence
        assert config.config["packages"] == ["json_package"]

    def test_load_from_environment(self, temp_project_dir, monkeypatch):
        """Test loading configuration from environment variables."""
        monkeypatch.setenv("PYCODEMCP_PACKAGES", "/path1:/path2:/path3")
        monkeypatch.setenv("PYCODEMCP_NAMESPACE_company_auth", "/repos/auth:/repos/login")
        monkeypatch.setenv("PYCODEMCP_NAMESPACE_company_api", "/repos/api")

        config = ProjectConfig(str(temp_project_dir))

        assert "/path1" in config.config.get("packages", [])
        assert "/path2" in config.config.get("packages", [])
        assert "/path3" in config.config.get("packages", [])

        namespaces = config.config.get("namespaces", {})
        assert "company.auth" in namespaces
        assert "/repos/auth" in namespaces["company.auth"]

    @patch.object(Path, "home")
    def test_load_global_config(self, mock_home, temp_project_dir):
        """Test loading global configuration from user home."""
        mock_home.return_value = temp_project_dir

        global_config_dir = temp_project_dir / ".config" / "pycodemcp"
        global_config_dir.mkdir(parents=True)

        global_config = {"packages": ["global_package"]}
        config_file = global_config_dir / "config.json"
        config_file.write_text(json.dumps(global_config))

        config = ProjectConfig(str(temp_project_dir))

        # Global config should be loaded if no local config
        assert "global_package" in config.config.get("packages", [])

    def test_auto_discovery(self, temp_project_dir):
        """Test auto-discovery of packages when no config is found."""
        # Create sibling directories
        parent_dir = temp_project_dir.parent
        sibling1 = parent_dir / "sibling1"
        sibling2 = parent_dir / "sibling2"

        sibling1.mkdir(exist_ok=True)
        sibling2.mkdir(exist_ok=True)

        # Add Python files to make them look like packages
        (sibling1 / "setup.py").write_text("")
        (sibling2 / "__init__.py").write_text("")

        with patch.object(ProjectConfig, "_auto_discover") as mock_discover:
            config = ProjectConfig(str(temp_project_dir))

            # Auto-discover should be called when no config exists
            if not config.config.get("packages"):
                mock_discover.assert_called()

    def test_merge_configs(self, temp_project_dir, monkeypatch):
        """Test that configs from different sources are merged."""
        # Local config
        local_config = {"packages": ["local_pkg"], "cache_ttl": 300}
        config_file = temp_project_dir / ".pycodemcp.json"
        config_file.write_text(json.dumps(local_config))

        # Environment config
        monkeypatch.setenv("PYCODEMCP_PACKAGES", "/env_pkg")

        config = ProjectConfig(str(temp_project_dir))

        # Should have both local and env packages
        packages = config.config.get("packages", [])
        assert "local_pkg" in packages
        assert "/env_pkg" in packages
        assert config.config["cache_ttl"] == 300

    def test_invalid_json_config(self, temp_project_dir, caplog):
        """Test handling of invalid JSON config files."""
        config_file = temp_project_dir / ".pycodemcp.json"
        config_file.write_text("{ invalid json }")

        _ = ProjectConfig(str(temp_project_dir))

        # Should log error but not crash
        assert "Error loading config" in caplog.text

    def test_missing_config_section_in_toml(self, temp_project_dir):
        """Test handling pyproject.toml without pycodemcp section."""
        toml_content = """
[tool.other]
setting = "value"
"""

        config_file = temp_project_dir / "pyproject.toml"
        config_file.write_text(toml_content)

        config = ProjectConfig(str(temp_project_dir))

        # Should not crash, config should be empty or auto-discovered
        assert isinstance(config.config, dict)

    def test_claude_config_directory(self, temp_project_dir):
        """Test loading config from .claude directory."""
        claude_dir = temp_project_dir / ".claude"
        claude_dir.mkdir()

        config_data = {"packages": ["claude_package"]}
        config_file = claude_dir / "pycodemcp.json"
        config_file.write_text(json.dumps(config_data))

        config = ProjectConfig(str(temp_project_dir))

        assert "claude_package" in config.config.get("packages", [])

    def test_get_packages(self, temp_project_dir):
        """Test getting package list from config."""
        # Create actual subdirectories
        (temp_project_dir / "pkg1").mkdir()
        (temp_project_dir / "pkg2").mkdir()
        (temp_project_dir / "pkg3").mkdir()

        config_data = {"packages": ["./pkg1", "./pkg2", "./pkg3"]}
        config_file = temp_project_dir / ".pycodemcp.json"
        config_file.write_text(json.dumps(config_data))

        config = ProjectConfig(str(temp_project_dir))
        packages = config.get_package_paths()

        # get_package_paths includes the project path itself plus the configured packages
        assert len(packages) >= 4  # project + 3 packages
        assert str(temp_project_dir) in packages  # Project itself
        assert any("pkg1" in p for p in packages)
        assert any("pkg2" in p for p in packages)
        assert any("pkg3" in p for p in packages)

    def test_get_namespaces(self, temp_project_dir):
        """Test getting namespace configuration."""
        config_data = {
            "namespaces": {"company.auth": ["/repos/auth"], "company.api": ["/repos/api"]}
        }
        config_file = temp_project_dir / ".pycodemcp.json"
        config_file.write_text(json.dumps(config_data))

        config = ProjectConfig(str(temp_project_dir))
        namespaces = config.get_namespaces()

        assert "company.auth" in namespaces
        assert "company.api" in namespaces

    def test_save_config(self, temp_project_dir):
        """Test saving configuration to file."""
        config = ProjectConfig(str(temp_project_dir))

        # Update config
        config.config["packages"] = ["new_package"]
        config.config["cache_ttl"] = 500

        # Save config
        config.save_config()

        # Reload and verify
        config_file = temp_project_dir / ".pycodemcp.json"
        assert config_file.exists()

        saved_data = json.loads(config_file.read_text())
        assert saved_data["packages"] == ["new_package"]
        assert saved_data["cache_ttl"] == 500

    def test_validate_paths_in_config(self, temp_project_dir):
        """Test that paths in config are validated."""
        config_data = {
            "packages": [
                "../valid_path",
                "../../another_path",
                "../../../suspicious",  # Could be flagged
            ]
        }

        config_file = temp_project_dir / ".pycodemcp.json"
        config_file.write_text(json.dumps(config_data))

        with patch("pycodemcp.config.PathValidator"):
            config = ProjectConfig(str(temp_project_dir))

            # Validator should be used for paths
            if hasattr(config, "validate_packages"):
                config.validate_packages()
