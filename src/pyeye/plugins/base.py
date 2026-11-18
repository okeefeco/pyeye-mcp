"""Base plugin class for extending analyzer capabilities."""

import ast
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..path_utils import normalize_path, relative_within
from ..scope_utils import ScopeLayout, package_scope_path, resolve_scope_paths

if TYPE_CHECKING:
    from ..analyzers.jedi_analyzer import JediAnalyzer

logger = logging.getLogger(__name__)

# Type alias for scope specification
Scope = str | list[str]


def _normalized(paths: Iterable[Path]) -> set[Path]:
    """Absolute, user-expanded, symlink-resolved paths, so equal locations compare equal."""
    return {normalize_path(Path(p).expanduser()) for p in paths}


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
        self.standalone_paths: list[Path] = []
        #: Config entries the path check refused (``ProjectConfig.rejected_paths``,
        #: #898). ``None`` until a completed check sets it: never a ``[]`` that
        #: nothing measured.
        self.rejected_paths: list[dict[str, str]] | None = None

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

    def _analyzer(self) -> "JediAnalyzer":
        """The project's shared analyzer (the server's instance; no ``pyeye.mcp`` import)."""
        from ..project_manager import get_project_manager

        return get_project_manager().get_analyzer(self.project_path.as_posix())

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

        Goes through the shared ``file_artifact_cache`` (#699), the one parse/cache
        implementation the primitives and handle enrichment use (#629), so a file
        is parsed once however many plugin tools walk it. *content* stays in the
        signature for callers that read the file first to pre-filter it.

        The returned tree is shared, so callers must not mutate it.

        A file that can't be read or parsed is skipped with a warning (#622), and
        any other error propagates. (5505cad briefly moved plugins off this cache
        on the suspicion that it caused #684, which was in fact parso's own cache
        GC, fixed in #706.)
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

    def set_standalone_paths(self, paths: list[Path]) -> None:
        """Set standalone script directories (searched by ``standalone`` and ``all``).

        Args:
            paths: Standalone script directories
        """
        self.standalone_paths = paths

    def set_rejected_paths(self, rejected: list[dict[str, str]] | None) -> None:
        """Set the config entries the path check refused (#898).

        Args:
            rejected: ``ProjectConfig.rejected_paths()``: ``{scope, path, reason, detail}``
                records, or ``None`` when the check couldn't complete
        """
        self.rejected_paths = rejected

    async def get_project_files(self, pattern: str = "*.py", scope: Scope = "main") -> list[Path]:
        """Get files from project based on scope.

        Note: Plugins default to 'main' scope since framework
        code is typically in the main project.

        Args:
            pattern: File pattern to search for (e.g., "*.py", "test_*.py")
            scope: A scope or a list of scopes, in the grammar of
                :data:`pyeye.scope_utils.SCOPE_FORMS`.

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
                        # Only a namespace path under the main project (#717: path_utils)
                        if relative_within(ns_path, self.project_path) is not None:
                            namespace_subdirs.append(ns_path)

                # Filter out files in namespace subdirectories
                filtered_files = []
                for f in files:
                    is_in_namespace = False
                    for ns_dir in namespace_subdirs:
                        if relative_within(f, ns_dir) is not None:
                            is_in_namespace = True
                            break
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

    def scope_layout(self) -> ScopeLayout:
        """This plugin's search-scope layout (the one :func:`resolve_scope_paths` reads)."""
        return ScopeLayout.from_parts(
            self.project_path,
            self.additional_paths,
            self.namespace_paths,
            self.standalone_paths,
        )

    async def _resolve_scope_to_paths(self, scope: Scope) -> set[Path]:
        """Resolve a scope to filesystem paths through the one resolver (#690).

        Args:
            scope: Scope specification (string or list of strings)

        Returns:
            Set of filesystem paths to search
        """
        return self._scope_paths(scope)

    def _scope_paths(self, scope: Scope, warn: bool = True) -> set[Path]:
        """Synchronous core of :meth:`_resolve_scope_to_paths`."""
        return resolve_scope_paths(
            scope, self.scope_layout(), warn=warn, owner=f"Plugin {self.name()}: "
        )

    def configured_scopes(self) -> dict[str, set[Path]]:
        """Map every scope this plugin is configured to search to the paths it covers.

        ``main`` always; ``packages`` and ``standalone`` when configured; then one
        ``namespace:<name>`` per configured namespace, sorted. Read from the same
        layout and resolver the search uses (:meth:`ScopeLayout.configured_scopes`).
        """
        return {
            name: _normalized(paths)
            for name, paths in self.scope_layout().configured_scopes().items()
        }

    async def envelope_extras(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Extra keys this plugin adds to *tool_name*'s envelope (``envelope=true``).

        The server merges them into ``{scope, searched, unsearched_scopes,
        results}`` without knowing which tool asked, so a tool-specific
        disclosure (``find_pydantic_models``' ``unplaced_classes``, #921) stays
        in its plugin. *arguments* are the call's bound arguments, ``scope``
        already resolved. Default: none.
        """
        _ = tool_name, arguments
        return {}

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
              searched, so an agent can widen the search (e.g. ``scope="all"``),
              then each ``package:<path>`` scope given whose directory doesn't
              exist, spelled as given (#842). A relative path is relative to the
              project (:func:`~pyeye.scope_utils.package_scope_path`).

            A scope with a config entry the path check refused
            (:attr:`rejected_paths`) is never ``searched`` and always
            ``unsearched``, whatever was asked: part of it can't be read (#898).

            A ``namespace:`` that isn't configured and an unknown scope search
            nothing, so they appear in neither list.
        """
        covered = _normalized(self._scope_paths(scope, warn=False))
        searched: list[str] = []
        unsearched: list[str] = []
        for name, paths in self.configured_scopes().items():
            # A path is searched when it is, or lies under, a searched root.
            # A scope with no directories (a namespace glob that matched nothing,
            # #872) searched nothing: unsearched, not vacuously "all searched".
            whole = bool(paths) and all(
                any(p == c or c in p.parents for c in covered) for p in paths
            )
            (searched if whole else unsearched).append(name)
        for s in [scope] if isinstance(scope, str) else scope:
            exists = (
                s.startswith("package:") and package_scope_path(s, self.scope_layout()).exists()
            )
            if exists and s not in searched:
                searched.append(s)
            # A missing package: path searched nothing; say so instead of only
            # logging it, so [] can't read as a measured empty (#842).
            elif s.startswith("package:") and not exists and s not in unsearched:
                unsearched.append(s)
        for name in dict.fromkeys(r["scope"] for r in self.rejected_paths or []):
            if name in searched:
                searched.remove(name)
            if name not in unsearched:
                unsearched.append(name)
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
