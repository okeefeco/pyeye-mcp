"""Base plugin class for extending analyzer capabilities."""

import ast
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Type alias for scope specification
Scope = str | list[str]


def _normalized(paths: Iterable[Path]) -> set[Path]:
    """Absolute, user-expanded, symlink-resolved paths, so equal locations compare equal."""
    return {Path(p).expanduser().resolve() for p in paths}


class AnalyzerPlugin(ABC):
    """Base class for analyzer plugins."""

    def __init__(self, project_path: str):
        """Initialize the plugin.

        Args:
            project_path: Root path of the project
        """
        self.project_path = Path(project_path)
        self.additional_paths: list[Path] = []
        self.namespace_paths: dict[str, list[Path]] = {}

    # Read/parse contract shared by every plugin (#622, #637): unreadable files and
    # unparseable user source are warned about and skipped; anything else, such as an
    # error raised while walking a parsed tree, propagates so that an internal failure
    # can never read as "nothing found".

    def _read_text_or_skip(self, path: Path) -> str | None:
        """Read a file synchronously, or warn and return ``None`` if it cannot be read as text."""
        try:
            return path.read_text()
        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"Plugin {self.name()}: error reading {path.as_posix()}: {e}")
            return None

    async def _read_source(self, path: Path) -> str | None:
        """Read a project file, or warn and return ``None`` if it cannot be read as text."""
        from ..async_utils import read_file_async

        try:
            return await read_file_async(path)
        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"Plugin {self.name()}: error reading {path.as_posix()}: {e}")
            return None

    def _parse_source(self, path: Path, content: str) -> ast.Module | None:  # noqa: ARG002
        """Parse user source, or warn and return ``None`` if it is not valid Python.

        Goes through the shared ``file_artifact_cache`` (#627), so plugins reuse the
        trees the primitives and handle enrichment parse, instead of re-parsing.
        *content* is kept in the signature for callers that read it to pre-filter.
        Callers must not mutate the returned tree: it is shared.
        """
        from .. import file_artifact_cache

        try:
            return file_artifact_cache.get_ast(path)
        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"Plugin {self.name()}: error reading {path.as_posix()}: {e}")
            return None
        except (SyntaxError, ValueError, RecursionError) as e:
            logger.warning(f"Plugin {self.name()}: error parsing {path.as_posix()}: {e}")
            return None

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

    def set_additional_paths(self, paths: list[Path]) -> None:
        """Set additional paths from configuration.

        Args:
            paths: List of additional package paths to include
        """
        self.additional_paths = paths
        logger.info(f"Plugin {self.name()}: Set {len(paths)} additional paths")

    def set_namespace_paths(self, namespaces: dict[str, list[str]]) -> None:
        """Set namespace package mappings.

        Args:
            namespaces: Dictionary mapping namespace names to their paths
        """
        self.namespace_paths = {ns: [Path(p) for p in paths] for ns, paths in namespaces.items()}
        logger.info(f"Plugin {self.name()}: Set {len(self.namespace_paths)} namespace mappings")

    async def get_project_files(self, pattern: str = "*.py", scope: Scope = "main") -> list[Path]:
        """Get files from project based on scope.

        Note: Plugins default to 'main' scope since framework
        code is typically in the main project.

        Args:
            pattern: File pattern to search for (e.g., "*.py", "test_*.py")
            scope: Search scope specification - can be:
                - "main": Only the main project (default for plugins)
                - "all": Include configured namespaces
                - "namespace:name": Specific namespace
                - List of scopes: Multiple scopes combined

        Returns:
            List of matching file paths
        """
        from ..async_utils import rglob_async

        search_paths = await self._resolve_scope_to_paths(scope)

        # Normalize scope to list for checking
        scopes = [scope] if isinstance(scope, str) else scope

        all_files = []
        for path in search_paths:
            files = await rglob_async(pattern, path)

            # If searching "main" scope only, exclude files in namespace subdirectories
            if "main" in scopes and path == self.project_path:
                # Get all namespace paths that are subdirectories of main project
                namespace_subdirs = []
                for ns_paths in self.namespace_paths.values():
                    for ns_path in ns_paths:
                        try:
                            # Check if namespace path is under main project
                            ns_path.relative_to(self.project_path)
                            namespace_subdirs.append(ns_path)
                        except ValueError:
                            # Not a subdirectory, ignore
                            pass

                # Filter out files in namespace subdirectories
                filtered_files = []
                for f in files:
                    is_in_namespace = False
                    for ns_dir in namespace_subdirs:
                        try:
                            f.relative_to(ns_dir)
                            is_in_namespace = True
                            break
                        except ValueError:
                            pass
                    if not is_in_namespace:
                        filtered_files.append(f)
                files = filtered_files

            all_files.extend(files)

        # Remove duplicates while preserving order
        seen = set()
        unique_files = []
        for f in all_files:
            if f not in seen:
                seen.add(f)
                unique_files.append(f)

        return unique_files

    async def _resolve_scope_to_paths(self, scope: Scope) -> set[Path]:
        """Resolve scope specification to actual filesystem paths.

        Args:
            scope: Scope specification (string or list of strings)

        Returns:
            Set of filesystem paths to search
        """
        return self._scope_paths(scope)

    def _scope_paths(self, scope: Scope, warn: bool = True) -> set[Path]:
        """Synchronous core of :meth:`_resolve_scope_to_paths`."""
        paths = set()

        # Normalize to list for uniform processing
        scopes = [scope] if isinstance(scope, str) else scope

        for s in scopes:
            if s == "main":
                # Just the main project
                paths.add(self.project_path)

            elif s == "all":
                # Everything: main + packages + namespaces
                paths.add(self.project_path)
                paths.update(self.additional_paths)
                # Add all namespace paths
                for ns_paths in self.namespace_paths.values():
                    paths.update(ns_paths)

            elif s == "packages":
                # All configured packages excluding main
                paths.update(self.additional_paths)

            elif s.startswith("namespace:"):
                # Specific namespace
                ns_name = s[10:]  # Remove "namespace:" prefix
                if ns_name in self.namespace_paths:
                    paths.update(self.namespace_paths[ns_name])
                else:
                    if warn:
                        logger.warning(f"Plugin {self.name()}: Namespace not found: {ns_name}")

            elif s.startswith("package:"):
                # Specific package path
                pkg_path = Path(s[8:])  # Remove "package:" prefix
                if pkg_path.exists():
                    paths.add(pkg_path)
                elif warn:
                    logger.warning(
                        f"Plugin {self.name()}: Package path does not exist: {pkg_path.as_posix()}"
                    )

            else:
                if warn:
                    logger.warning(f"Plugin {self.name()}: Unknown scope specification: {s}")

        return paths

    def configured_scopes(self) -> dict[str, set[Path]]:
        """Map every scope this plugin is configured to search to the paths it covers.

        In a stable order: ``main`` always; ``packages`` when configured packages
        add paths beyond the main project and the namespaces (``additional_paths``
        also holds those, as :func:`pyeye.mcp.server.initialize_plugins` sets it);
        then one ``namespace:<name>`` per configured namespace, sorted.
        """
        namespace_paths = {
            f"namespace:{name}": _normalized(self.namespace_paths[name])
            for name in sorted(self.namespace_paths)
        }
        main = _normalized([self.project_path])
        packages = _normalized(self.additional_paths) - main
        for ns in namespace_paths.values():
            packages -= ns
        scopes: dict[str, set[Path]] = {"main": main}
        if packages:
            scopes["packages"] = packages
        scopes.update(namespace_paths)
        return scopes

    def describe_scope(self, scope: Scope) -> tuple[list[str], list[str]]:
        """Report what a search over ``scope`` covers, for the plugin-tool envelope (#594).

        Coverage is decided by path, from the same resolution the search uses
        (:meth:`_resolve_scope_to_paths`), so ``searched`` can't claim more than
        was read.

        Args:
            scope: Scope specification, with aliases already expanded

        Returns:
            ``(searched, unsearched_scopes)``:

            - ``searched``: the configured scopes (see :meth:`configured_scopes`)
              whose paths were all searched, then each ``package:<path>`` scope
              given that exists.
            - ``unsearched_scopes``: the configured scopes with any path not
              searched, so an agent can widen the search (e.g. ``scope="all"``).

            A ``namespace:`` that isn't configured, a missing ``package:`` path and
            an unknown scope search nothing, so they appear in neither list.
        """
        covered = _normalized(self._scope_paths(scope, warn=False))
        searched: list[str] = []
        unsearched: list[str] = []
        for name, paths in self.configured_scopes().items():
            (searched if paths <= covered else unsearched).append(name)
        for s in [scope] if isinstance(scope, str) else scope:
            if s.startswith("package:") and Path(s[8:]).exists() and s not in searched:
                searched.append(s)
        return searched, unsearched

    async def _get_scope_roots(self, scope: Scope) -> list[Path]:
        """Get all project roots based on scope.

        Helper method for plugins that need to search for non-Python files
        like templates or migrations.

        Args:
            scope: Scope specification

        Returns:
            List of root paths to search
        """
        return list(await self._resolve_scope_to_paths(scope))
