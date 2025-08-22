"""Performance settings for Python Code Intelligence MCP Server."""

import logging
import os

logger = logging.getLogger(__name__)


class PerformanceSettings:
    """Configurable performance settings for the MCP server.

    All settings can be configured via environment variables to tune
    performance for different workloads and codebase sizes.
    """

    def __init__(self) -> None:
        """Initialize performance settings from environment variables."""
        # Project management settings
        self.max_projects: int = self._get_int_env(
            "PYCODEMCP_MAX_PROJECTS", 10, min_val=1, max_val=1000
        )

        # Cache settings
        self.cache_ttl: int = self._get_int_env(
            "PYCODEMCP_CACHE_TTL",
            300,  # 5 minutes default
            min_val=0,
            max_val=86400,  # Max 24 hours
        )

        # File watcher settings
        self.watcher_debounce: float = self._get_float_env(
            "PYCODEMCP_WATCHER_DEBOUNCE", 0.5, min_val=0.0, max_val=10.0
        )

        # File handling settings
        self.max_file_size: int = self._get_int_env(
            "PYCODEMCP_MAX_FILE_SIZE",
            1048576,  # 1MB default
            min_val=1024,
            max_val=104857600,  # 1KB to 100MB
        )

        # Concurrency settings
        self.max_workers: int = self._get_int_env("PYCODEMCP_MAX_WORKERS", 4, min_val=1, max_val=32)

        # Analysis settings
        self.analysis_timeout: float = self._get_float_env(
            "PYCODEMCP_ANALYSIS_TIMEOUT",
            30.0,  # 30 seconds default
            min_val=1.0,
            max_val=300.0,  # 1 second to 5 minutes
        )

        # Memory management
        self.enable_memory_profiling: bool = self._get_bool_env(
            "PYCODEMCP_ENABLE_MEMORY_PROFILING", False
        )

        # Performance monitoring
        self.enable_performance_metrics: bool = self._get_bool_env(
            "PYCODEMCP_ENABLE_PERFORMANCE_METRICS", False
        )

    def _get_int_env(
        self, key: str, default: int, min_val: int | None = None, max_val: int | None = None
    ) -> int:
        """Get integer value from environment variable with validation.

        Args:
            key: Environment variable name
            default: Default value if not set
            min_val: Minimum allowed value
            max_val: Maximum allowed value

        Returns:
            Validated integer value
        """
        try:
            value = int(os.getenv(key, str(default)))

            if min_val is not None and value < min_val:
                logger.warning(f"{key}={value} below minimum {min_val}, using {min_val}")
                return min_val

            if max_val is not None and value > max_val:
                logger.warning(f"{key}={value} above maximum {max_val}, using {max_val}")
                return max_val

            return value
        except ValueError:
            logger.warning(f"Invalid value for {key}, using default {default}")
            return default

    def _get_float_env(
        self,
        key: str,
        default: float,
        min_val: float | None = None,
        max_val: float | None = None,
    ) -> float:
        """Get float value from environment variable with validation.

        Args:
            key: Environment variable name
            default: Default value if not set
            min_val: Minimum allowed value
            max_val: Maximum allowed value

        Returns:
            Validated float value
        """
        try:
            value = float(os.getenv(key, str(default)))

            if min_val is not None and value < min_val:
                logger.warning(f"{key}={value} below minimum {min_val}, using {min_val}")
                return min_val

            if max_val is not None and value > max_val:
                logger.warning(f"{key}={value} above maximum {max_val}, using {max_val}")
                return max_val

            return value
        except ValueError:
            logger.warning(f"Invalid value for {key}, using default {default}")
            return default

    def _get_bool_env(self, key: str, default: bool) -> bool:
        """Get boolean value from environment variable.

        Args:
            key: Environment variable name
            default: Default value if not set

        Returns:
            Boolean value
        """
        env_val = os.getenv(key, "").lower()
        if not env_val:
            return default
        return env_val in ("true", "1", "yes", "on")

    def get_summary(self) -> str:
        """Get a summary of current settings.

        Returns:
            Formatted string with all settings
        """
        return f"""Performance Settings:
  Project Management:
    max_projects: {self.max_projects}

  Caching:
    cache_ttl: {self.cache_ttl}s

  File Watching:
    watcher_debounce: {self.watcher_debounce}s

  File Handling:
    max_file_size: {self.max_file_size} bytes ({self.max_file_size / 1048576:.2f} MB)

  Concurrency:
    max_workers: {self.max_workers}

  Analysis:
    analysis_timeout: {self.analysis_timeout}s

  Monitoring:
    enable_memory_profiling: {self.enable_memory_profiling}
    enable_performance_metrics: {self.enable_performance_metrics}
"""


# Global settings instance
settings = PerformanceSettings()
