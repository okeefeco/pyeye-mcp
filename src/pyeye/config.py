"""Configuration management for PyEye."""

import json
import logging
import os
from pathlib import Path
from typing import Any

from .constants import CONFIG_DIR, CONFIG_FILES, OVERRIDE_FILE, PROJECT_NAME
from .validation import PathValidator, ValidationError

logger = logging.getLogger(__name__)


class ProjectConfig:
    """Manages project-specific configuration for code intelligence."""

    # Config file names to check (in order of precedence)
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
                    if PROJECT_NAME in data:
                        self.config.update(data[PROJECT_NAME])
                    else:
                        self.config.update(data)

            elif config_path.suffix in [".yaml", ".yml"]:
                with open(config_path) as f:
                    import yaml  # type: ignore[import-untyped]

                    data = yaml.safe_load(f)
                    if PROJECT_NAME in data:
                        self.config.update(data[PROJECT_NAME])
                    else:
                        self.config.update(data)

            elif config_path.name == "pyproject.toml":
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib

                with open(config_path, "rb") as f:
                    data = tomllib.load(f)

                    # Read PyEye-specific config first
                    if "tool" in data and PROJECT_NAME in data["tool"]:
                        self.config.update(data["tool"][PROJECT_NAME])

                    # Auto-detect source layouts from build backend metadata
                    # Only apply if no packages already configured
                    if not self.config.get("packages"):
                        self._detect_source_layout(data)

        except Exception as e:
            logger.error(f"Error loading config from {config_path.as_posix()}: {e}")

    def _load_global_config(self) -> None:
        """Load global configuration from user home.

        Global config provides defaults that can be overridden by project config.
        """
        global_configs = [
            Path.home() / CONFIG_DIR / "config.json",
            Path.home() / f".{PROJECT_NAME}.json",
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

    def _detect_setuptools_layout(self, tool_config: dict[str, Any]) -> list[str]:
        """Extract setuptools [tool.setuptools.packages.find.where].

        Args:
            tool_config: The [tool] section from pyproject.toml

        Returns:
            List of detected paths
        """
        paths = []
        if "setuptools" in tool_config:
            setuptools_config = tool_config["setuptools"]
            if "packages" in setuptools_config:
                packages_config = setuptools_config["packages"]
                if "find" in packages_config:
                    where = packages_config["find"].get("where", [])
                    if isinstance(where, list):
                        paths.extend(where)
                    elif isinstance(where, str):
                        paths.append(where)
        return paths

    def _detect_poetry_layout(self, tool_config: dict[str, Any]) -> list[str]:
        """Extract poetry [tool.poetry.packages].

        Args:
            tool_config: The [tool] section from pyproject.toml

        Returns:
            List of detected paths
        """
        paths = []
        if "poetry" in tool_config:
            poetry_config = tool_config["poetry"]
            if "packages" in poetry_config:
                for package in poetry_config["packages"]:
                    if "from" in package:
                        paths.append(package["from"])
        return paths

    def _detect_hatch_layout(self, tool_config: dict[str, Any]) -> list[str]:
        """Extract hatch [tool.hatch.build.targets.wheel.sources].

        Args:
            tool_config: The [tool] section from pyproject.toml

        Returns:
            List of detected paths
        """
        paths = []
        if "hatch" in tool_config:
            hatch_config = tool_config["hatch"]
            if "build" in hatch_config:
                build_config = hatch_config["build"]
                if "targets" in build_config and "wheel" in build_config["targets"]:
                    wheel_config = build_config["targets"]["wheel"]
                    if "sources" in wheel_config:
                        sources = wheel_config["sources"]
                        if isinstance(sources, list):
                            paths.extend(sources)
                        elif isinstance(sources, str):
                            paths.append(sources)
        return paths

    def _detect_pdm_layout(self, tool_config: dict[str, Any]) -> list[str]:
        """Extract PDM [tool.pdm.build.package-dir].

        Args:
            tool_config: The [tool] section from pyproject.toml

        Returns:
            List of detected paths
        """
        paths = []
        if "pdm" in tool_config:
            pdm_config = tool_config["pdm"]
            if "build" in pdm_config:
                build_config = pdm_config["build"]
                if "package-dir" in build_config:
                    paths.append(build_config["package-dir"])
        return paths

    def _add_detected_paths(self, detected_paths: list[str]) -> None:
        """Validate and add detected paths to config.

        Args:
            detected_paths: List of paths detected from build backend metadata
        """
        if not detected_paths:
            return

        valid_paths = []
        for path in detected_paths:
            full_path = self.project_path / path
            if full_path.exists() and full_path.is_dir():
                valid_paths.append(path)

        if valid_paths:
            self.config.setdefault("packages", []).extend(valid_paths)
            logger.info(f"Auto-detected source layout from pyproject.toml: {valid_paths}")

    def _detect_source_layout(self, pyproject_data: dict[str, Any]) -> None:
        """Detect source layout from pyproject.toml build backend metadata.

        Supports multiple build backends:
        - setuptools: [tool.setuptools.packages.find.where]
        - poetry: [tool.poetry.packages]
        - hatch: [tool.hatch.build.targets.wheel.sources]
        - pdm: [tool.pdm.build.package-dir]

        Args:
            pyproject_data: Parsed pyproject.toml data
        """
        if "tool" not in pyproject_data:
            return

        tool_config = pyproject_data["tool"]
        detected_paths: list[str] = []

        # Delegate to specialized methods
        detected_paths.extend(self._detect_setuptools_layout(tool_config))
        detected_paths.extend(self._detect_poetry_layout(tool_config))
        detected_paths.extend(self._detect_hatch_layout(tool_config))
        detected_paths.extend(self._detect_pdm_layout(tool_config))

        self._add_detected_paths(detected_paths)

    def _discover_src_layout(self) -> bool:
        """Check for src/ layout and add if found.

        Returns:
            True if src/ layout was found and added, False otherwise
        """
        src_dir = self.project_path / "src"
        if src_dir.exists() and src_dir.is_dir():
            # Check if src/ contains Python packages
            has_packages = any(
                (item / "__init__.py").exists() for item in src_dir.iterdir() if item.is_dir()
            )
            if has_packages:
                self.config.setdefault("packages", []).append("src")
                logger.info("Auto-detected source layout: src/")
                return True
        return False

    def _discover_sibling_packages(self) -> list[str]:
        """Discover sibling packages in parent directory.

        Returns:
            List of sibling package paths
        """
        potential_packages = []
        parent = self.project_path.parent

        if parent != self.project_path:
            try:
                for sibling in parent.iterdir():
                    try:
                        if (
                            sibling.is_dir()
                            and sibling != self.project_path
                            and (any(sibling.glob("*.py")) or (sibling / "setup.py").exists())
                        ):
                            potential_packages.append(str(sibling))
                    except (PermissionError, OSError):
                        continue
            except (PermissionError, OSError):
                pass

        return potential_packages

    def _discover_venv_packages(self) -> list[str]:
        """Discover packages in virtualenv site-packages.

        Returns:
            List of site-packages paths
        """
        potential_packages = []
        venv_paths = [
            self.project_path / "venv" / "lib",
            self.project_path / ".venv" / "lib",
            self.project_path / "env" / "lib",
        ]

        for venv_path in venv_paths:
            if venv_path.exists():
                for site_packages in venv_path.rglob("site-packages"):
                    potential_packages.append(str(site_packages))

        return potential_packages

    def _auto_discover(self) -> None:
        """Auto-discover package locations."""
        # Check for src layout first (most specific pattern)
        if self._discover_src_layout():
            return  # Don't look for other patterns if src/ found

        # Discover sibling packages and virtualenv packages
        potential_packages = []
        potential_packages.extend(self._discover_sibling_packages())
        potential_packages.extend(self._discover_venv_packages())

        if potential_packages:
            logger.info(f"Auto-discovered packages: {potential_packages}")
            self.config.setdefault("packages", []).extend(potential_packages)

    def _process_package_path(self, package: str) -> list[str]:
        """Process a single package path, handling globs and validation.

        Args:
            package: Package path (may contain glob patterns)

        Returns:
            List of validated paths
        """
        paths = []
        try:
            if "*" in package:
                from glob import glob

                expanded = glob(os.path.expanduser(package))
                for exp_path in expanded:
                    validated = PathValidator.validate_path(exp_path)
                    paths.append(str(validated))
            else:
                # Resolve relative to project directory
                if not os.path.isabs(package):
                    package = os.path.join(str(self.project_path), package)
                validated = PathValidator.validate_path(package)
                if validated.exists():
                    paths.append(str(validated))
        except ValidationError as e:
            logger.warning(f"Skipping invalid package path {package}: {e}")

        return paths

    def _process_namespace_paths(self, namespaces: dict[str, list[str]]) -> list[str]:
        """Process namespace paths, handling globs and validation.

        Args:
            namespaces: Dictionary mapping namespace to paths

        Returns:
            List of validated paths
        """
        paths = []
        for _namespace, ns_paths in namespaces.items():
            for ns_path in ns_paths:
                try:
                    if "*" in ns_path:
                        from glob import glob

                        expanded = glob(os.path.expanduser(ns_path))
                        for exp_path in expanded:
                            validated = PathValidator.validate_path(exp_path)
                            paths.append(str(validated))
                    else:
                        validated = PathValidator.validate_path(ns_path)
                        if validated.exists():
                            paths.append(str(validated))
                except ValidationError as e:
                    logger.warning(
                        f"Skipping invalid namespace path {Path(ns_path).as_posix()}: {e}"
                    )

        return paths

    def _deduplicate_paths(self, paths: list[str]) -> list[str]:
        """Remove duplicate paths while preserving order.

        Args:
            paths: List of paths (may contain duplicates)

        Returns:
            List of unique paths in original order
        """
        seen = set()
        unique_paths: list[str] = []
        for path in paths:
            path_str = Path(path).as_posix()
            if path_str not in seen:
                seen.add(path_str)
                unique_paths.append(path_str)

        return unique_paths

    def get_package_paths(self) -> list[str]:
        """Get all configured package paths.

        Returns:
            List of absolute paths to packages
        """
        paths = []

        # Add configured packages
        for package in self.config.get("packages", []):
            paths.extend(self._process_package_path(package))

        # Add namespace paths
        namespaces = self.config.get("namespaces", {})
        paths.extend(self._process_namespace_paths(namespaces))

        # Always include current project
        paths.insert(0, str(self.project_path))

        # Remove duplicates while preserving order
        return self._deduplicate_paths(paths)

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

    def get_standalone_config(self) -> dict[str, Any]:
        """Get standalone scripts configuration.

        Returns:
            Dictionary with standalone directory configuration including:
            - dirs: List of directories containing standalone scripts
            - recursive: Whether to scan subdirectories (default True)
            - file_pattern: Pattern to match files (default "*.py")
            - exclude_patterns: Patterns to exclude (default [])
        """
        standalone = self.config.get("standalone", {})
        if not standalone:
            return {
                "dirs": [],
                "recursive": True,
                "file_pattern": "*.py",
                "exclude_patterns": [],
            }

        return {
            "dirs": standalone.get("dirs", []),
            "recursive": standalone.get("recursive", True),
            "file_pattern": standalone.get("file_pattern", "*.py"),
            "exclude_patterns": standalone.get("exclude_patterns", []),
        }

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
        "standalone": {
            "dirs": ["notebooks", "scripts", "examples"],
            "recursive": True,
            "file_pattern": "*.py",
            "exclude_patterns": ["**/test_*", "**/__pycache__/**"],
        },
        "exclude": ["**/tests/**", "**/migrations/**", "**/__pycache__/**"],
        "cache": {"ttl_seconds": 300, "max_size_mb": 100},
    }

    config_path = Path(project_path) / f".{PROJECT_NAME}.json.example"
    with open(config_path, "w") as f:
        json.dump(example, f, indent=2)

    print(f"Created example config at {config_path.as_posix()}")
