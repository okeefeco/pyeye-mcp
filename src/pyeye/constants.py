"""Constants for PyEye configuration and paths."""

# Project name
PROJECT_NAME = "pyeye"

# Config file names (in order of precedence)
CONFIG_FILES = [
    f".{PROJECT_NAME}.json",
    f".{PROJECT_NAME}.yaml",
    f".{PROJECT_NAME}.yml",
    "pyproject.toml",
    f".claude/{PROJECT_NAME}.json",
]

# The file configure_packages saves, in the project root (docs fact security.writes.config)
CONFIG_FILE = f".{PROJECT_NAME}.json"

# Override file name
OVERRIDE_FILE = f".{PROJECT_NAME}.override.json"

# Global config directory
CONFIG_DIR = f".config/{PROJECT_NAME}"

# Global config files, relative to the user's home, in the order they're tried:
# the first that exists is loaded (docs fact config.files.global)
GLOBAL_CONFIG_FILES = (f"{CONFIG_DIR}/config.json", f".{PROJECT_NAME}.json")

# Metrics/data directory
METRICS_DIR = f".{PROJECT_NAME}/metrics"

# pyproject.toml section name
TOML_SECTION = f"tool.{PROJECT_NAME}"

# Directory names that hold no project source: virtual envs, caches, VCS and IDE
# metadata, build output. ONE list for the project scan, the file watcher and
# scope classification, applied by ``project_layout.excluded_scan_dir`` (#1104),
# which still scans such a directory when it is a package.
EXCLUDED_DIRS = frozenset(
    {
        ".venv",
        "venv",
        ".env",
        "env",
        "__pycache__",
        ".git",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        ".eggs",
        "*.egg-info",
        "build",
        "dist",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
    }
)
