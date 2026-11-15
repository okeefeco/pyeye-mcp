"""Namespace package resolution for distributed Python packages."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class NamespaceResolver:
    """Resolves Python namespace packages across multiple repositories."""

    def __init__(self) -> None:
        """Initialize the namespace resolver."""
        # Maps namespace to list of paths
        self.namespace_paths: dict[str, list[Path]] = {}
        # Cache of package structures
        self.package_cache: dict[str, dict] = {}

    def register_namespace(self, namespace: str, paths: list[str]) -> None:
        """Register paths for a namespace package.

        Args:
            namespace: Package namespace (e.g., "mycompany.plugins")
            paths: List of paths containing parts of this namespace
        """
        resolved_paths = []
        for path in paths:
            p = Path(path).resolve()
            if p.exists():
                resolved_paths.append(p)
                logger.info(f"Registered {namespace} at {p}")
            else:
                logger.warning(f"Path does not exist: {Path(path).as_posix()}")

        self.namespace_paths[namespace] = resolved_paths
