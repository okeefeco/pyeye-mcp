"""Configuration management for Python Code Intelligence MCP."""

import os
import json
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


class ProjectConfig:
    """Manages project-specific configuration for code intelligence."""
    
    # Config file names to check (in order of precedence)
    CONFIG_FILES = [
        ".pycodemcp.json",
        ".pycodemcp.yaml",
        ".pycodemcp.yml",
        "pyproject.toml",  # Can read from [tool.pycodemcp] section
        ".claude/pycodemcp.json",
    ]
    
    def __init__(self, project_path: str = "."):
        """Initialize configuration for a project.
        
        Args:
            project_path: Root path of the project
        """
        self.project_path = Path(project_path).resolve()
        self.config: Dict[str, Any] = {}
        self.load_config()
        
    def load_config(self):
        """Load configuration from various sources."""
        # 1. Check for config files in project
        for config_file in self.CONFIG_FILES:
            config_path = self.project_path / config_file
            if config_path.exists():
                self._load_from_file(config_path)
                break
                
        # 2. Check environment variables
        self._load_from_env()
        
        # 3. Check for global config
        self._load_global_config()
        
        # 4. Auto-discover if no config found
        if not self.config.get("packages"):
            self._auto_discover()
            
    def _load_from_file(self, config_path: Path):
        """Load configuration from a file."""
        logger.info(f"Loading config from {config_path}")
        
        try:
            if config_path.suffix == ".json":
                with open(config_path) as f:
                    data = json.load(f)
                    self.config.update(data.get("pycodemcp", data))
                    
            elif config_path.suffix in [".yaml", ".yml"]:
                with open(config_path) as f:
                    import yaml
                    data = yaml.safe_load(f)
                    self.config.update(data.get("pycodemcp", data))
                    
            elif config_path.name == "pyproject.toml":
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib
                    
                with open(config_path, "rb") as f:
                    data = tomllib.load(f)
                    if "tool" in data and "pycodemcp" in data["tool"]:
                        self.config.update(data["tool"]["pycodemcp"])
                        
        except Exception as e:
            logger.error(f"Error loading config from {config_path}: {e}")
            
    def _load_from_env(self):
        """Load configuration from environment variables."""
        # PYCODEMCP_PACKAGES=/path/to/pkg1:/path/to/pkg2
        if "PYCODEMCP_PACKAGES" in os.environ:
            packages = os.environ["PYCODEMCP_PACKAGES"].split(":")
            self.config.setdefault("packages", []).extend(packages)
            
        # PYCODEMCP_NAMESPACE_company=/repos/company-*
        for key, value in os.environ.items():
            if key.startswith("PYCODEMCP_NAMESPACE_"):
                namespace = key.replace("PYCODEMCP_NAMESPACE_", "").replace("_", ".")
                self.config.setdefault("namespaces", {})[namespace] = value.split(":")
                
    def _load_global_config(self):
        """Load global configuration from user home."""
        global_configs = [
            Path.home() / ".config" / "pycodemcp" / "config.json",
            Path.home() / ".pycodemcp.json",
        ]
        
        for config_path in global_configs:
            if config_path.exists():
                try:
                    with open(config_path) as f:
                        global_config = json.load(f)
                        # Global config has lower precedence
                        for key, value in global_config.items():
                            self.config.setdefault(key, value)
                        break
                except Exception as e:
                    logger.error(f"Error loading global config: {e}")
                    
    def _auto_discover(self):
        """Auto-discover package locations."""
        # Look for common patterns
        parent = self.project_path.parent
        
        # Check for sibling packages
        potential_packages = []
        if parent != self.project_path:
            for sibling in parent.iterdir():
                if sibling.is_dir() and sibling != self.project_path:
                    # Check if it's a Python package
                    if any(sibling.glob("*.py")) or (sibling / "setup.py").exists():
                        potential_packages.append(str(sibling))
                        
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
            
    def get_package_paths(self) -> List[str]:
        """Get all configured package paths.
        
        Returns:
            List of absolute paths to packages
        """
        paths = []
        
        # Add configured packages
        for package in self.config.get("packages", []):
            # Support glob patterns
            if "*" in package:
                from glob import glob
                expanded = glob(os.path.expanduser(package))
                paths.extend(expanded)
            else:
                path = Path(package).expanduser().resolve()
                if path.exists():
                    paths.append(str(path))
                    
        # Add namespace paths
        for namespace, ns_paths in self.config.get("namespaces", {}).items():
            for ns_path in ns_paths:
                if "*" in ns_path:
                    from glob import glob
                    expanded = glob(os.path.expanduser(ns_path))
                    paths.extend(expanded)
                else:
                    path = Path(ns_path).expanduser().resolve()
                    if path.exists():
                        paths.append(str(path))
                        
        # Always include current project
        paths.insert(0, str(self.project_path))
        
        # Remove duplicates while preserving order
        seen = set()
        unique_paths = []
        for path in paths:
            if path not in seen:
                seen.add(path)
                unique_paths.append(path)
                
        return unique_paths
        
    def get_namespaces(self) -> Dict[str, List[str]]:
        """Get configured namespace packages.
        
        Returns:
            Dictionary mapping namespace to paths
        """
        return self.config.get("namespaces", {})
        
    def save_config(self, config_path: Optional[Path] = None):
        """Save current configuration to a file.
        
        Args:
            config_path: Path to save to (defaults to .pycodemcp.json)
        """
        if config_path is None:
            config_path = self.project_path / ".pycodemcp.json"
            
        try:
            with open(config_path, "w") as f:
                json.dump(self.config, f, indent=2)
            logger.info(f"Saved config to {config_path}")
        except Exception as e:
            logger.error(f"Error saving config: {e}")


def create_example_config(project_path: str = "."):
    """Create an example configuration file.
    
    Args:
        project_path: Where to create the config
    """
    example = {
        "packages": [
            ".",
            "../my-shared-library",
            "~/repos/company-utils",
            "/absolute/path/to/package"
        ],
        "namespaces": {
            "mycompany": [
                "~/repos/mycompany-auth",
                "~/repos/mycompany-api",
                "~/repos/mycompany-core"
            ],
            "plugins": [
                "./plugins/*",
                "~/repos/community-plugins/*"
            ]
        },
        "exclude": [
            "**/tests/**",
            "**/migrations/**",
            "**/__pycache__/**"
        ],
        "cache": {
            "ttl_seconds": 300,
            "max_size_mb": 100
        }
    }
    
    config_path = Path(project_path) / ".pycodemcp.json.example"
    with open(config_path, "w") as f:
        json.dump(example, f, indent=2)
        
    print(f"Created example config at {config_path}")
    return config_path