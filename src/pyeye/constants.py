"""Constants for PyEye configuration and paths."""

# Project name constants
PROJECT_NAME = "pyeye"
LEGACY_PROJECT_NAME = "pycodemcp"  # For backward compatibility

# Config file names (in order of precedence)
CONFIG_FILES = [
    f".{PROJECT_NAME}.json",
    f".{PROJECT_NAME}.yaml",
    f".{PROJECT_NAME}.yml",
    f".{LEGACY_PROJECT_NAME}.json",  # Legacy support
    f".{LEGACY_PROJECT_NAME}.yaml",  # Legacy support
    f".{LEGACY_PROJECT_NAME}.yml",  # Legacy support
    "pyproject.toml",  # Can read from [tool.pyeye] or [tool.pycodemcp]
    f".claude/{PROJECT_NAME}.json",
    f".claude/{LEGACY_PROJECT_NAME}.json",  # Legacy support
]

# Override file names
OVERRIDE_FILE = f".{PROJECT_NAME}.override.json"
LEGACY_OVERRIDE_FILE = f".{LEGACY_PROJECT_NAME}.override.json"

# Global config directory names
CONFIG_DIR = f".config/{PROJECT_NAME}"
LEGACY_CONFIG_DIR = f".config/{LEGACY_PROJECT_NAME}"

# Metrics/data directory
METRICS_DIR = f".{PROJECT_NAME}/metrics"
LEGACY_METRICS_DIR = f".{LEGACY_PROJECT_NAME}/metrics"

# pyproject.toml section names
TOML_SECTION = f"tool.{PROJECT_NAME}"
LEGACY_TOML_SECTION = f"tool.{LEGACY_PROJECT_NAME}"
