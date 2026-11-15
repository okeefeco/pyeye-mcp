"""Namespace package resolution for distributed Python packages."""

import logging
from pathlib import Path

from .path_utils import normalize_path, path_to_key

logger = logging.getLogger(__name__)


class NamespaceResolver:
    """Resolves Python namespace packages across multiple repositories."""

    def __init__(self) -> None:
        """Initialize the namespace resolver."""
        # Every registration, by namespace, across ALL projects: a diagnostic
        # view only. Never merge it into an analyzer (#748); use namespaces_for.
        self.namespace_paths: dict[str, list[Path]] = {}
        # Project root key (path_utils.path_to_key) -> namespace -> paths (#748).
        self._by_project: dict[str, dict[str, list[Path]]] = {}
        # Cache of package structures
        self.package_cache: dict[str, dict] = {}

    def namespaces_for(self, project: str | Path) -> dict[str, list[Path]]:
        """The namespaces registered FOR *project* (#748), never another project's."""
        return dict(self._by_project.get(path_to_key(project), {}))

    def register_namespace(
        self, namespace: str, paths: list[str], project: str | Path | None = None
    ) -> None:
        """Register paths for a namespace package, for one project (#748).

        A registration applies only to *project*'s analyzer. One without a
        project (the pre-#748 call shape) is recorded but applies to no
        analyzer, and logs a warning naming the namespace: a process-wide
        registration leaked one project's namespaces into every other.

        Args:
            namespace: Package namespace (e.g., "mycompany.plugins")
            paths: List of paths containing parts of this namespace
            project: The project root the namespace belongs to.
        """
        resolved_paths = []
        for path in paths:
            p = normalize_path(path)
            if p.exists():
                resolved_paths.append(p)
                logger.info(f"Registered {namespace} at {p}")
            else:
                logger.warning(f"Path does not exist: {Path(path).as_posix()}")

        self.namespace_paths[namespace] = resolved_paths
        if project is None:
            logger.warning(
                f"Namespace {namespace!r} registered without a project: it applies to "
                "no project's analyzer (#748). Pass project=<root>."
            )
            return
        self._by_project.setdefault(path_to_key(project), {})[namespace] = resolved_paths
