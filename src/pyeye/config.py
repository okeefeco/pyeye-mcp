"""Configuration management for Python Code Intelligence MCP."""

import json
import logging
import os
from pathlib import Path
from typing import Any

from .constants import (
    CONFIG_DIR,
    CONFIG_FILES,
    LEGACY_CONFIG_DIR,
    LEGACY_PROJECT_NAME,
    OVERRIDE_FILE,
    PROJECT_NAME,
)
from .validation import PathValidator, ValidationError

logger = logging.getLogger(__name__)


class ProjectConfig:
    """Manages project-specific configuration for code intelligence."""

    # Config file names to check (in order of precedence)
    # Supports both new (.pyeye) and legacy (.pycodemcp) names for backward compatibility
    CONFIG_FILES = CONFIG_FILES

    def __init__(self, project_path: str = ".") -> None:
        """Initialize configuration for a project.

        Args:
            project_path: Root path of the project
        """
        self.project_path = Path(project_path).resolve()
        self.config: dict[str, Any] = {}
        self.load_config()

    def load_config(self) -> None:
        """Load configuration from various sources.

        Loading order (later sources override earlier ones):
        1. Global config (~/.config/pyeye/config.json)
        2. Project config files (.pyeye.json, pyproject.toml, etc.)
        3. Override file (.pyeye.override.json) - for local development
        4. Auto-discovery (if no packages configured)
        """
        # 1. Load global config first (lowest precedence)
        self._load_global_config()

        # 2. Load project config files
        for config_file in self.CONFIG_FILES:
            config_path = self.project_path / config_file
            if config_path.exists():
                self._load_from_file(config_path)
                break

        # 3. Load override file (highest precedence)
        override_path = self.project_path / OVERRIDE_FILE
        if override_path.exists():
            self._load_from_file(override_path)

        # 4. Auto-discover if no config found
        if not self.config.get("packages"):
            self._auto_discover()

    def _load_from_file(self, config_path: Path) -> None:
        """Load configuration from a file."""
        logger.info(f"Loading config from {config_path.as_posix()}")

        try:
            if config_path.suffix == ".json":
                with open(config_path) as f:
                    data = json.load(f)
                    # Support both new and legacy top-level keys
                    if PROJECT_NAME in data:
                        self.config.update(data[PROJECT_NAME])
                    elif LEGACY_PROJECT_NAME in data:
                        self.config.update(data[LEGACY_PROJECT_NAME])
                    else:
                        self.config.update(data)

            elif config_path.suffix in [".yaml", ".yml"]:
                with open(config_path) as f:
                    import yaml  # type: ignore[import-untyped]

                    data = yaml.safe_load(f)
                    # Support both new and legacy top-level keys
                    if PROJECT_NAME in data:
                        self.config.update(data[PROJECT_NAME])
                    elif LEGACY_PROJECT_NAME in data:
                        self.config.update(data[LEGACY_PROJECT_NAME])
                    else:
                        self.config.update(data)

            elif config_path.name == "pyproject.toml":
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib

                with open(config_path, "rb") as f:
                    data = tomllib.load(f)
                    # Support both new [tool.pyeye] and legacy [tool.pycodemcp] sections
                    # New name takes precedence
                    if "tool" in data:
                        if PROJECT_NAME in data["tool"]:
                            self.config.update(data["tool"][PROJECT_NAME])
                        elif LEGACY_PROJECT_NAME in data["tool"]:
                            self.config.update(data["tool"][LEGACY_PROJECT_NAME])

        except Exception as e:
            logger.error(f"Error loading config from {config_path.as_posix()}: {e}")

    def _load_global_config(self) -> None:
        """Load global configuration from user home.

        Global config provides defaults that can be overridden by project config.
        Supports both new (.pyeye) and legacy (.pycodemcp) paths for backward compatibility.
        """
        global_configs = [
            Path.home() / CONFIG_DIR / "config.json",  # New location
            Path.home() / f".{PROJECT_NAME}.json",  # New location
            Path.home() / LEGACY_CONFIG_DIR / "config.json",  # Legacy support
            Path.home() / f".{LEGACY_PROJECT_NAME}.json",  # Legacy support
        ]

        for config_path in global_configs:
            if config_path.exists():
                try:
                    with open(config_path) as f:
                        global_config = json.load(f)
                        # Global config loaded first, so just update
                        self.config.update(global_config)
                        logger.info(f"Loaded global config from {config_path.as_posix()}")
                        break
                except Exception as e:
                    logger.error(f"Error loading global config: {e}")

    def _auto_discover(self) -> None:
        """Auto-discover package locations."""
        # Look for common patterns
        parent = self.project_path.parent

        # Check for sibling packages
        potential_packages = []
        if parent != self.project_path:
            try:
                for sibling in parent.iterdir():
                    try:
                        if (
                            sibling.is_dir()
                            and sibling != self.project_path
                            and (any(sibling.glob("*.py")) or (sibling / "setup.py").exists())
                        ):
                            # It's a Python package
                            potential_packages.append(str(sibling))
                    except (PermissionError, OSError):
                        # Skip inaccessible directories
                        continue
            except (PermissionError, OSError):
                # Can't access parent directory
                pass

        # Check for virtualenv site-packages
        venv_paths = [
            self.project_path / "venv" / "lib",
            self.project_path / ".venv" / "lib",
            self.project_path / "env" / "lib",
        ]

        for venv_path in venv_paths:
            if venv_path.exists():
                # Find site-packages
                for site_packages in venv_path.rglob("site-packages"):
                    potential_packages.append(str(site_packages))

        if potential_packages:
            logger.info(f"Auto-discovered packages: {potential_packages}")
            self.config.setdefault("packages", []).extend(potential_packages)

    def get_package_paths(self) -> list[str]:
        """Get all configured package paths.

        Returns:
            List of absolute paths to packages
        """
        paths = []

        # Add configured packages
        for package in self.config.get("packages", []):
            try:
                # Support glob patterns
                if "*" in package:
                    from glob import glob

                    expanded = glob(os.path.expanduser(package))
                    for exp_path in expanded:
                        # Validate each expanded path
                        validated = PathValidator.validate_path(exp_path)
                        paths.append(str(validated))
                else:
                    # Resolve relative to project directory
                    if not os.path.isabs(package):
                        package = os.path.join(str(self.project_path), package)
                    # Validate the path
                    validated = PathValidator.validate_path(package)
                    if validated.exists():
                        paths.append(str(validated))
            except ValidationError as e:
                logger.warning(f"Skipping invalid package path {package}: {e}")
                continue

        # Add namespace paths
        for _namespace, ns_paths in self.config.get("namespaces", {}).items():
            for ns_path in ns_paths:
                try:
                    if "*" in ns_path:
                        from glob import glob

                        expanded = glob(os.path.expanduser(ns_path))
                        for exp_path in expanded:
                            # Validate each expanded path
                            validated = PathValidator.validate_path(exp_path)
                            paths.append(str(validated))
                    else:
                        # Validate the path
                        validated = PathValidator.validate_path(ns_path)
                        if validated.exists():
                            paths.append(str(validated))
                except ValidationError as e:
                    logger.warning(
                        f"Skipping invalid namespace path {Path(ns_path).as_posix()}: {e}"
                    )
                    continue

        # Always include current project
        paths.insert(0, str(self.project_path))

        # Remove duplicates while preserving order
        seen = set()
        unique_paths: list[str] = []
        for path in paths:
            path_str = Path(path).as_posix()
            if path_str not in seen:
                seen.add(path_str)
                unique_paths.append(path_str)

        return unique_paths

    def get_namespaces(self) -> dict[str, list[str]]:
        """Get configured namespace packages.

        Returns:
            Dictionary mapping namespace to paths
        """
        namespaces = self.config.get("namespaces", {})
        return dict(namespaces) if namespaces else {}

    def get_scope_defaults(self) -> dict[str, Any]:
        """Get configured scope defaults.

        Returns:
            Dictionary with global and method-specific scope defaults
        """
        defaults = self.config.get("scope_defaults", {})
        return dict(defaults) if defaults else {}

    def get_scope_aliases(self) -> dict[str, Any]:
        """Get configured scope aliases.

        Returns:
            Dictionary mapping alias names to scope specifications
        """
        aliases = self.config.get("scope_aliases", {})
        return dict(aliases) if aliases else {}

    def save_config(self, config_path: Path | None = None) -> None:
        """Save current configuration to a file.

        Args:
            config_path: Path to save to (defaults to .pyeye.json)
        """
        if config_path is None:
            config_path = self.project_path / f".{PROJECT_NAME}.json"

        try:
            with open(config_path, "w") as f:
                json.dump(self.config, f, indent=2)
            logger.info(f"Saved config to {config_path.as_posix()}")
        except Exception as e:
            logger.error(f"Error saving config: {e}")


def create_example_config(project_path: str = ".") -> None:
    """Create an example configuration file.

    Args:
        project_path: Where to create the config
    """
    example = {
        "packages": [
            ".",
            "../my-shared-library",
            "~/repos/company-utils",
            "/absolute/path/to/package",
        ],
        "namespaces": {
            "mycompany": [
                "~/repos/mycompany-auth",
                "~/repos/mycompany-api",
                "~/repos/mycompany-core",
            ],
            "plugins": ["./plugins/*", "~/repos/community-plugins/*"],
        },
        "exclude": ["**/tests/**", "**/migrations/**", "**/__pycache__/**"],
        "cache": {"ttl_seconds": 300, "max_size_mb": 100},
    }

    config_path = Path(project_path) / f".{PROJECT_NAME}.json.example"
    with open(config_path, "w") as f:
        json.dump(example, f, indent=2)

    print(f"Created example config at {config_path.as_posix()}")
