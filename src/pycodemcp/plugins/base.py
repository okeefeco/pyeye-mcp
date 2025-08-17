"""Base plugin class for extending analyzer capabilities."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any


class AnalyzerPlugin(ABC):
    """Base class for analyzer plugins."""

    def __init__(self, project_path: str):
        """Initialize the plugin.

        Args:
            project_path: Root path of the project
        """
        self.project_path = Path(project_path)

    @abstractmethod
    def name(self) -> str:
        """Return the plugin name."""
        pass

    @abstractmethod
    def detect(self) -> bool:
        """Detect if this plugin should be activated for the project.

        Returns:
            True if the plugin should be activated
        """
        pass

    def register_tools(self) -> dict[str, Callable]:
        """Register additional MCP tools provided by this plugin.

        Returns:
            Dictionary mapping tool names to callables
        """
        return {}

    def augment_symbol_results(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Augment symbol search results with plugin-specific information.

        Args:
            results: Original symbol search results

        Returns:
            Augmented results
        """
        return results

    def find_patterns(self, pattern_name: str) -> list[dict[str, Any]]:
        """Find plugin-specific patterns in the code.

        Args:
            pattern_name: Name of the pattern to find

        Returns:
            List of pattern matches
        """
        _ = pattern_name  # Mark as intentionally unused
        return []

    def get_framework_components(self) -> dict[str, list[str]]:
        """Get framework-specific components.

        Returns:
            Dictionary mapping component types to file paths
        """
        return {}
