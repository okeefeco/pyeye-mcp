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

# Override file name
OVERRIDE_FILE = f".{PROJECT_NAME}.override.json"

# Global config directory
CONFIG_DIR = f".config/{PROJECT_NAME}"

# Metrics/data directory
METRICS_DIR = f".{PROJECT_NAME}/metrics"

# pyproject.toml section name
TOML_SECTION = f"tool.{PROJECT_NAME}"
