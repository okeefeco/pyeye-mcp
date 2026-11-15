"""Jedi-based analyzer for PyEye."""

import ast
import asyncio
import logging
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NamedTuple

import jedi

from .. import file_artifact_cache, settings
from .._jedi_project import make_project
from ..config import ProjectConfig
from ..exceptions import AnalysisError, ProjectNotFoundError
from ..handle import Handle
from ..import_analyzer import resolve_relative_import
from ..path_utils import absolute_path, normalize_path, path_to_key, relative_within
from ..project_layout import (
    detect_src_layout,
    layout_key,
    module_name_for_file,
)
from ..resolver import Resolved, resolve_item
from ..scope_utils import (
    ScopedCache,
    ScopeLayout,
    SmartScopeResolver,
    namespace_directory_structure,
    parallel_search,
    resolve_scope_paths,
)
from ..symbol_parser import get_parent_and_member, is_compound_symbol, parse_compound_symbol
from . import project_graph
from .base_resolution import (
    build_import_table,
    build_module_defines,
    build_star_sources,
    extract_definitions,
    resolve_base,
)

logger = logging.getLogger(__name__)

# Type alias for scope specification
Scope = str | list[str]


def _parse_or_record(py_file: Path, unparseable: list[str]) -> ast.Module | None:
    """A project-wide scan's AST for *py_file*, or ``None`` when it can't be parsed (#729).

    A :class:`SyntaxError` (the same mapping as #703's ``parse_own_source``)
    records the file's POSIX path in *unparseable*, so the scan discloses it
    instead of silently dropping it.  Anything else propagates to the caller's
    existing handling (#704).
    """
    try:
        return file_artifact_cache.get_ast(py_file)
    except SyntaxError:
        unparseable.append(path_to_key(py_file))
        return None


class Importers(NamedTuple):
    """What :meth:`JediAnalyzer.find_importers` found (#668).

    Attributes:
        named: ``(importer_dotted_module, importer_file)`` pairs, deduped by
            module and sorted by module name.
        unnamed: Files that import the target but have no module name (a path
            part that isn't a Python identifier, such as ``my-script.py`` or
            ``tools-dir/x.py``), POSIX-sorted. They are real dependents with no
            handle, reported so they are never silently dropped.
    """

    named: list[tuple[str, Path]]
    unnamed: list[Path]
    #: Files in scope that couldn't be parsed, POSIX (#729).
    unparseable: tuple[str, ...] = ()


def _jedi_sys_path(paths: Iterable[str | Path]) -> list[str]:
    """Spell *paths* the way Jedi compares them: OS-native strings, deduped.

    Jedi names a module by ``str(module_path).startswith(sys_path_entry)``
    (``jedi.inference.sys_path.transform_path_to_dotted``), where the module
    path is OS-native. A forward-slash entry never matches a backslash path on
    Windows, so Jedi fell back to the project root and named src-layout
    modules ``src.<pkg>…`` there (#625). This is an OS operation, so the
    native form is right here; our own attributes stay ``Path``/posix.
    """
    out: list[str] = []
    for raw in paths:
        native = os.fspath(Path(raw))
        if native not in out:
            out.append(native)
    return out


def _scope_key(scope: Scope | None) -> str:
    """A stable cache key for *scope*, as passed (order kept: it is the caller's)."""
    if scope is None or isinstance(scope, str):
        return str(scope)
    return "|".join(scope)


def _dotted_prefixes(dotted: str) -> list[str]:
    """``a.b.c`` -> ``["a", "a.b", "a.b.c"]``: every module a dotted import names."""
    parts = dotted.split(".")
    return [".".join(parts[: i + 1]) for i in range(len(parts))]


def _class_fact(node: ast.ClassDef, py_file: Path) -> project_graph.ClassFact:
    """The facts a subclass stub needs, without keeping the AST node (#397, #713)."""
    return project_graph.ClassFact(
        name=node.name,
        file=py_file,
        line=node.lineno,
        # end_lineno is the class body's last line (Python 3.8+ AST), carried so
        # the subclasses edge reports a real line span without re-deriving a Jedi
        # Name (#445). Falling back to lineno keeps line_end >= line_start.
        end_line=node.end_lineno or node.lineno,
        column=node.col_offset,
    )


def _subclass_info(fqn: str, fact: project_graph.ClassFact, direct_parent: str) -> dict[str, Any]:
    """One ``find_subclasses`` result record."""
    return {
        "name": fact.name,
        "full_name": fqn,
        "file": fact.file.as_posix(),
        "line": fact.line,
        "end_line": fact.end_line,
        "column": fact.column,
        "direct_parent": direct_parent,
        "is_direct": True,
    }


class JediAnalyzer:
    """Wrapper around Jedi for semantic Python analysis."""

    def __init__(
        self,
        project_path: str = ".",
        config: ProjectConfig | None = None,
        namespace_config: dict[str, list[str]] | None = None,
    ):
        """Initialize the Jedi analyzer.

        Args:
            project_path: Root path of the project to analyze
            config: Optional project configuration for smart defaults
            namespace_config: Optional namespace package mappings
                (``{"ns_name": ["repo_root_path", ...]}``) to include in
                the Jedi project's ``added_sys_path`` at init time.  This
                ensures ``full_name`` values include the namespace prefix
                from the very first query.

        Raises:
            ProjectNotFoundError: If the project path doesn't exist
        """
        # Make the root absolute so every location.file is absolute whatever
        # spelling the caller used (#603). abspath, not resolve(): an already
        # absolute path must keep its spelling (no /var -> /private/var on macOS,
        # no RUNNER~1 expansion on Windows) so callers' own paths still match.
        self.project_path = absolute_path(project_path)
        self.additional_paths: list[Path] = []  # For additional package paths
        self.namespace_paths: dict[str, list[Path]] = {}  # For namespace packages
        self.standalone_paths: list[Path] = []  # For standalone script directories
        self.source_roots: list[Path] = []  # For src-layout roots (e.g., src/)
        # Ordered (sys.path-precedence) roots passed to jedi.Project; a future
        # containment enumerator relies on this being a stable, list-derived
        # source. Populated below before jedi.Project is constructed (#423).
        self.added_sys_path: list[Path] = []
        self._additional_projects: dict[Path, jedi.Project] = {}  # Cached Jedi projects
        self.config = config

        # Initialize scope utilities
        self.smart_resolver = SmartScopeResolver(config)
        self.scoped_cache = ScopedCache(ttl_seconds=settings.settings.cache_ttl)

        # Validate project path exists
        if not self.project_path.exists():
            raise ProjectNotFoundError(self.project_path.as_posix())

        # Apply namespace_config immediately so namespace_paths is populated
        # before the Jedi project is created.
        if namespace_config:
            self.namespace_paths = {
                ns: [Path(p) for p in paths] for ns, paths in namespace_config.items()
            }

        try:
            # Get additional sys paths from config (e.g., src/ layout, sibling packages)
            added_sys_path: list[str] = []
            resolved_project = normalize_path(self.project_path)
            if config:
                package_paths = config.get_package_paths()
                in_project: list[Path] = []
                for pkg_path in package_paths:
                    pkg = normalize_path(pkg_path)
                    if pkg == resolved_project or not pkg.exists():
                        continue
                    # A root inside the project keeps project_path's spelling, as
                    # in the no-config branch below: files are enumerated under
                    # that spelling, and location.file must keep it (#603, #714).
                    rel = relative_within(pkg, self.project_path)
                    if rel is not None:
                        pkg = self.project_path / rel
                        in_project.append(pkg)
                    added_sys_path.append(pkg.as_posix())
                    logger.info(f"Adding {pkg.as_posix()} to Jedi sys path")
                if in_project:
                    self.source_roots = in_project
            else:
                # No config: apply the same src-layout rule ProjectConfig's
                # auto-discovery uses, so an analyzer built without config names
                # files the way a configured one does (#625).  Only src/ is
                # detected here: sibling/venv discovery and global config stay
                # config-only.
                #
                # The root keeps project_path's spelling, NOT a resolved one.
                # project_path is deliberately unresolved (#603), and files are
                # enumerated under it, so a resolved src root (a symlink target,
                # a Windows long name for an 8.3 path) would never match them:
                # every module would fall back to the project root and be
                # named ``src.<pkg>…``.
                src = detect_src_layout(self.project_path)
                if src is not None:
                    added_sys_path.append(src.as_posix())
                    self.source_roots = [src]
                    logger.info(f"Adding {src.as_posix()} to Jedi sys path (src layout)")

            # Add namespace repo roots to Jedi's sys_path so full_name values
            # include the namespace prefix from the first query.
            for ns_paths in self.namespace_paths.values():
                for ns_path in ns_paths:
                    resolved = normalize_path(ns_path)
                    if resolved.exists() and resolved.as_posix() not in added_sys_path:
                        added_sys_path.append(resolved.as_posix())
                        logger.info(f"Adding namespace root {resolved.as_posix()} to Jedi sys path")

            # Store the FINAL merged list (src-layout + namespace roots) as the
            # public attribute, typed as Path, in the same sys.path-precedence
            # order that is handed to jedi.Project (#423).  Jedi gets RESOLVED
            # paths: it resolves the module paths it compares them with, so a
            # symlinked or short-name spelling would never match (#714).  The
            # caller's spelling stays in project_path / source_roots, for
            # display and for the file <-> module mapper.
            jedi_sys_path = list(
                dict.fromkeys(normalize_path(p).as_posix() for p in added_sys_path)
            )
            self.added_sys_path = [Path(p) for p in jedi_sys_path]

            # When the project_path IS a Python package (has __init__.py),
            # Jedi must be rooted at the PARENT so that the package name is
            # included in full_name values.
            jedi_root = normalize_path(self.project_path)
            self._jedi_root_is_parent = False
            if (jedi_root / "__init__.py").exists():
                jedi_root = jedi_root.parent
                self._jedi_root_is_parent = True

            # #722: never jedi.Project directly; make_project drops Jedi's own
            # subprocess directory from the base sys.path.  The root and
            # added_sys_path are the RESOLVED, Jedi-facing spellings (#714).
            self.project = make_project(
                jedi_root,
                added_sys_path=_jedi_sys_path(jedi_sys_path) if jedi_sys_path else (),
            )
            logger.info(f"Initialized JediAnalyzer for {self.project_path.as_posix()}")
        except Exception as e:
            logger.error(f"Failed to initialize Jedi project: {e}")
            raise AnalysisError(
                f"Failed to initialize analyzer for {self.project_path.as_posix()}",
                file_path=self.project_path.as_posix(),
                error=str(e),
            ) from e

    @property
    def layout_key(self) -> str:
        """This analyzer's effective-layout identity (:func:`pyeye.project_layout.layout_key`).

        Computed on each access rather than cached: ``set_additional_paths``,
        ``set_namespace_paths`` and ``set_standalone_paths`` change the layout
        after construction.
        """
        return layout_key(self)

    def set_additional_paths(self, paths: list[Path]) -> None:
        """Set additional paths from ProjectManager.

        Args:
            paths: List of additional package paths to include in analysis
        """
        self.additional_paths = paths
        logger.info(f"Set {len(paths)} additional paths for {self.project_path}")

    def set_namespace_paths(self, namespaces: dict[str, list[str]]) -> None:
        """Set namespace package mappings.

        For namespace packages (no ``__init__.py``), the parent directories of
        each namespace path must be in Jedi's ``added_sys_path`` so that Jedi
        resolves ``full_name`` values with the namespace prefix.  For example,
        if namespace ``aac`` has path ``/repos/aac-catalog/aac/logical/``, then
        ``/repos/aac-catalog/`` must be in Jedi's sys path so Jedi reports
        ``aac.logical.patterns.X`` instead of ``logical.patterns.X``.

        Args:
            namespaces: Dictionary mapping namespace names to their paths
        """
        self.namespace_paths = {ns: [Path(p) for p in paths] for ns, paths in namespaces.items()}
        logger.info(f"Set {len(self.namespace_paths)} namespace mappings for {self.project_path}")

        # Add namespace repo roots to Jedi's sys_path so full_name values
        # include the namespace prefix.  The declared paths in .pyeye.json are
        # repo roots that CONTAIN the namespace package directory.  E.g., for
        # "aac": ["../aac-catalog"], the path ../aac-catalog/ contains aac/ as
        # a subdirectory.  Adding aac-catalog/ to sys_path lets Jedi resolve
        # "aac.logical.patterns.X" instead of just "logical.patterns.X".
        ns_sys_paths: set[str] = set()
        for ns_paths in self.namespace_paths.values():
            for ns_path in ns_paths:
                resolved = normalize_path(ns_path)
                if resolved.exists():
                    ns_sys_paths.add(resolved.as_posix())

        if ns_sys_paths:
            # Merge with existing added_sys_path and recreate the Jedi project
            existing = list(self.project.added_sys_path or [])
            merged = _jedi_sys_path(set(existing) | ns_sys_paths)
            jedi_root = self.project.path
            self.project = make_project(jedi_root, added_sys_path=merged)
            logger.info(f"Updated Jedi sys_path with {len(ns_sys_paths)} namespace parent dirs")

    def set_standalone_paths(self, paths: list[Path]) -> None:
        """Set standalone script directories.

        Args:
            paths: List of directories containing standalone Python scripts
        """
        self.standalone_paths = paths
        logger.info(f"Set {len(paths)} standalone script directories for {self.project_path}")
        # Invalidate cache when standalone paths change
        self.scoped_cache.invalidate_all()

    # LIVE (not deprecated): the AST name-index search (#457) behind ``find_symbol``
    # and ``_resolve_simple_type`` — i.e. behind ``resolve``. Do not remove.
    async def index_unparseable_files(self) -> tuple[str, ...]:
        """Project files the bare-name index couldn't parse, POSIX-sorted (#729).

        A definition in such a file is invisible to bare-name ``resolve``, so a
        miss there is not proof of absence.  Built with (and cached alongside)
        the name index.
        """
        files: tuple[str, ...] = await self._project_index(project_graph.get_index_unparseable)
        return files

    async def _project_index(self, getter: Any) -> Any:
        """Run one of ``project_graph``'s whole-project index getters off the event loop.

        Snapshot before listing files: a watcher invalidation landing between the
        listing and the build then stops a stale index being cached (#617).
        """
        generation = project_graph.generation(self.project_path.as_posix())
        all_files = await self.get_project_files(pattern="*.py", scope="all")
        file_to_module = {f: self._get_import_path_for_file(f) for f in all_files}
        return await asyncio.to_thread(
            getter,
            self.project_path.as_posix(),
            all_files,
            file_to_module,
            generation,
            layout_key=self.layout_key,
        )

    async def find_member_definitions(self, name: str) -> list[Any]:
        """Every method or class-body attribute named *name*, project-wide (#508).

        The fallback behind ``resolve_name`` rule 4: these definitions are never
        bare-name *indexed* (#457), so ``find_symbol`` can't see them.  Dunder
        names are never returned.  Same index build, caching and scope
        filtering as :meth:`_search_all_scopes`.
        """
        return await self._search_all_scopes(name, members=True)

    async def _search_all_scopes(
        self,
        name: str,
        scope: Scope | None = None,
        fuzzy: bool = False,
        *,
        members: bool = False,
    ) -> list[Any]:
        """Find every project definition of *name* across the requested scope.

        **Live, not deprecated.** An earlier docstring marked this for removal
        alongside the legacy methods; that is wrong. It is the search behind
        ``find_symbol`` and ``_resolve_simple_type`` — i.e. behind ``resolve`` —
        and the legacy methods that once used it are gone (#505).

        Looks *name* up in the whole-project AST name-index (built once and
        cached in :mod:`pyeye.analyzers.project_graph`, outside the
        ``file_artifact_cache`` LRU) and filters results to the scope's resolved
        paths. Replaces ``jedi.Project.search``, whose 30-parsed-file cap
        silently dropped definitions of high-frequency names (#457). The index is
        built whole-project so completeness never depends on scope or cache size;
        scope narrowing happens here, at lookup time.

        Args:
            name: Symbol name to search for.
            scope: Search scope — "main", "all", "namespace:name", etc.
                   Defaults to "all".
            fuzzy: When True, match any indexed name *containing* ``name``
                   (substring), mirroring the old search; else exact name.
            members: Search the member index (methods and class attributes,
                #508) instead of the name index.

        Returns:
            ``DefinitionSentinel`` objects for every matching definition,
            deduplicated by ``(name, file, line)``.
        """
        effective_scope = scope if scope is not None else "all"

        # Build (or reuse) the whole-project name index off the event loop. The
        # build is parse-bound and paid once per project; lookups are O(1) dict
        # access. Scope is NOT baked into the build (that would poison the
        # project-keyed cache for other scopes) — it is applied below at lookup.
        index = await self._project_index(
            project_graph.get_member_index if members else project_graph.get_name_index
        )

        if fuzzy:
            candidates = [d for key, defs in index.items() if name in key for d in defs]
        else:
            candidates = index.get(name, [])
        if not candidates:
            return []

        # Narrow to the requested scope at lookup time, then dedup by
        # (name, file, line) — preserving the historical key.
        scope_dirs = [
            normalize_path(d) for d in await self._resolve_scope_to_paths(effective_scope)
        ]

        results: list[Any] = []
        seen: set[tuple[str, str | None, int]] = set()
        for r in candidates:
            if r.module_path is None:
                continue
            resolved_mp = normalize_path(r.module_path)
            if not any(relative_within(resolved_mp, d) is not None for d in scope_dirs):
                continue
            key = (r.name, resolved_mp.as_posix(), r.line)
            if key not in seen:
                seen.add(key)
                results.append(r)
        return results

    async def get_project_files(
        self,
        pattern: str = "*.py",
        scope: Scope | None = None,
        method_name: str | None = None,
    ) -> list[Path]:
        """Get files from project based on scope specification.

        Args:
            pattern: File pattern to search for (e.g., "*.py", "test_*.py")
            scope: Search scope specification - can be:
                - "main": Just the main project
                - "all": Everything configured (default) - includes standalone scripts
                - "packages": All configured packages excluding main
                - "standalone": Only standalone script directories
                - "namespace:name": Specific namespace (e.g., "namespace:aac")
                - "namespace:name.sub": Sub-namespace (e.g., "namespace:aac.tools")
                - "package:path": Specific package path
                - List of scopes: Multiple scopes combined
                - None: Use smart default based on method_name
            method_name: Name of the calling method (for smart defaults)

        Returns:
            List of matching file paths

        Examples:
            # Get all Python files in main project only
            files = await analyzer.get_project_files(scope="main")

            # Get test files from a specific namespace
            files = await analyzer.get_project_files("test_*.py", "namespace:mycompany.tests")

            # Get files from multiple scopes
            files = await analyzer.get_project_files(scope=["main", "namespace:utils"])

            # Use smart defaults
            files = await analyzer.get_project_files(method_name="list_modules")
        """
        # Apply smart defaults if no scope specified
        if scope is None and method_name:
            scope = self.smart_resolver.get_smart_default(method_name)
        elif scope is None:
            scope = "all"  # Fallback default

        # Resolve aliases
        scope = self.smart_resolver.resolve_aliases(scope)

        # Check cache first
        cache_key = f"files:{pattern}"
        cached = self.scoped_cache.get(cache_key, scope)
        if cached is not None:
            return list(cached) if isinstance(cached, list) else []

        search_paths = await self._resolve_scope_to_paths(scope)

        # Use parallel search for better performance
        unique_files = await parallel_search(pattern, list(search_paths))

        # Cache the result
        self.scoped_cache.set(cache_key, unique_files, scope)

        return unique_files

    def scope_layout(self) -> ScopeLayout:
        """This analyzer's search-scope layout (the one :func:`resolve_scope_paths` reads)."""
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
        return resolve_scope_paths(scope, self.scope_layout())

    def _resolve_namespace_scope(self, namespace: str) -> set[Path]:
        """The paths of *namespace* (e.g. ``"aac"`` or ``"aac.tools"``)."""
        return resolve_scope_paths(f"namespace:{namespace}", self.scope_layout(), warn=False)

    def _get_namespace_directory_structure(self, ns_path: Path) -> set[Path]:
        """The package directories in namespace repository *ns_path*."""
        return namespace_directory_structure(ns_path)

    def _get_import_path_for_file(self, py_file: Path) -> str | None:
        """Return the dotted module name for *py_file*, as Jedi's ``full_name`` spells it.

        Delegates to :func:`pyeye.project_layout.module_name_for_file`, the one
        file → module mapper (#625). It covers src roots, a project that is
        itself a package, additional packages and namespace roots, so the name
        index, ``find_importers`` and ``resolve(<file>)`` all agree.

        Args:
            py_file: Path to the Python file

        Returns:
            Import path string, or None if it can't be determined
        """
        return module_name_for_file(self, py_file)

    async def find_symbol(
        self,
        name: str,
        fuzzy: bool = False,
        scope: Scope | None = None,
    ) -> list[dict[str, Any]]:
        """Find symbol definitions across all configured scopes.

        Searches the main project plus any configured additional packages
        and namespace packages.

        Args:
            name: Symbol name to search for (supports compound symbols like "Model.__init__")
            fuzzy: Enable fuzzy matching
            scope: Search scope - "main", "all", "namespace:name", etc.
                   Defaults to "all" (searches everything configured).

        Returns:
            List of symbol matches with location information
        """
        # Check if this is a compound symbol (e.g., "Model.__init__")
        if is_compound_symbol(name):
            return await self._find_compound_symbol(name, scope)

        results = []

        try:
            search_results = await self._search_all_scopes(name, scope, fuzzy=fuzzy)

            for result in search_results:
                if not fuzzy and result.name != name:
                    continue

                try:
                    results.append(await self._serialize_name(result))
                except Exception as e:
                    # Log but don't fail entire search for one bad result
                    logger.warning(f"Could not serialize result {result.name}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error in find_symbol: {e}")
            # Don't raise - return partial results if any
            if not results:
                # Convert Path objects in exception to strings for serialization
                error_str = str(e)
                # Special handling for exceptions that contain Path objects
                if hasattr(e, "args") and e.args and any(isinstance(arg, Path) for arg in e.args):
                    converted_args = []
                    for arg in e.args:
                        if isinstance(arg, Path):
                            converted_args.append(arg.as_posix())
                        else:
                            converted_args.append(str(arg))
                    error_str = " ".join(converted_args) if converted_args else str(e)

                raise AnalysisError(
                    f"Failed to search for symbol '{name}'",
                    operation="find_symbol",
                    symbol=name,
                    error=error_str,
                ) from e

        return results

    async def _find_compound_symbol(
        self,
        name: str,
        scope: Scope | None = None,
    ) -> list[dict[str, Any]]:
        """Find compound symbol definitions (e.g., "Model.__init__").

        Args:
            name: Compound symbol name (e.g., "Model.__init__", "module.Class.method")
            scope: Search scope - "main", "all", "namespace:name", etc.

        Returns:
            List of symbol matches with location information
        """
        results = []

        # Parse the compound symbol
        components, valid = parse_compound_symbol(name)
        if not valid:
            logger.warning(f"Invalid compound symbol: {name}")
            return []

        if len(components) < 2:
            # Not actually a compound symbol
            return await self.find_symbol(name, scope=scope)

        try:
            # Get parent and member names
            _, member_name = get_parent_and_member(components)

            # First, find the parent symbol (class or module) across all scopes
            parent_results = await self._search_all_scopes(components[-2], scope)

            for parent_result in parent_results:
                # Check if this parent matches our full parent path
                parent_full_name = parent_result.full_name
                if parent_full_name and not parent_full_name.endswith(components[-2]):
                    continue

                # Get the parent's defined names (methods, attributes, etc.)
                try:
                    parent_names = self._enclosed_definitions(parent_result)

                    # Search for the member within the parent's scope
                    for defined_name in parent_names:
                        if defined_name.name == member_name:
                            # Found the member in this parent
                            try:
                                serialized = await self._serialize_name(defined_name)
                                # Ensure the full name reflects the compound nature
                                if "full_name" in serialized:
                                    # Verify this is the right match
                                    full_name = serialized["full_name"]
                                    # Check if it matches our expected pattern
                                    if components[-2] in full_name and member_name in full_name:
                                        results.append(serialized)
                            except Exception as e:
                                logger.warning(f"Could not serialize {defined_name.name}: {e}")
                                continue
                except Exception as e:
                    logger.debug(f"Could not get defined names for {parent_result.name}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error in _find_compound_symbol: {e}")
            # Return empty list rather than raising
            return []

        return results

    def _enclosed_definitions(self, parent: Any) -> list[Any]:
        """Return the direct child definitions of a class/module result (AST).

        Replaces a Jedi ``Name.defined_names()`` call: re-parses the parent's
        file via the cached AST and returns its direct members
        (``DefinitionSentinel``) — deterministic, no Jedi (#449). Lets compound
        resolution (``Class.method`` / ``module.Class``) reach members without
        carrying them in the global name index.

        Args:
            parent: A name-index result (class or module) to enumerate.

        Returns:
            The parent's direct child definitions, or ``[]`` if unavailable.
        """
        if parent.module_path is None or not parent.full_name:
            return []
        path = Path(parent.module_path)
        try:
            tree = file_artifact_cache.get_ast(path)
        except (OSError, SyntaxError, ValueError):
            return []
        module_name = self._get_import_path_for_file(path)
        parent_full = parent.full_name
        return [
            d
            for d in extract_definitions(tree, module_name, path)
            if d.full_name == f"{parent_full}.{d.name}"
        ]

    # LIVE (not deprecated): used by ``find_importers``, which backs the
    # ``imported_by`` edge. ``ImportAnalyzer`` delegates to the same shared helper.
    @staticmethod
    def _resolve_relative_import(
        level: int, module: str | None, importer_module: str, importer_is_package: bool
    ) -> str | None:
        """Resolve an ``ast.ImportFrom`` to an absolute module path.

        ``level`` is the number of leading dots and ``module`` is the text after
        them (``None`` for ``from . import x``).  Absolute imports
        (``level == 0``) are returned unchanged.  Relative imports are resolved
        against *importer_module* using Python's package semantics:

        - a regular module ``pkg.sub.mod`` has package ``pkg.sub``; ``level=1``
          anchors there and each extra level strips one trailing component.
        - a package ``pkg.sub`` (its ``__init__``) IS its own package; ``level=1``
          anchors at ``pkg.sub`` itself.

        Without this, a relative import's bare tail (e.g. ``exceptions`` from
        ``from .exceptions import X``) is mis-classified as external and the
        importer is never attributed to the target's ``imported_by`` (#343).

        Args:
            level: Number of leading dots (0 = absolute import).
            module: Module text after the dots, or ``None`` for ``from . import x``.
            importer_module: Dotted path of the module doing the import.
            importer_is_package: ``True`` when the importer is a package
                ``__init__`` (its module name already denotes the package).

        Returns:
            The absolute dotted module path, or ``None`` if it cannot be resolved
            (e.g. the relative level walks above the project root).

        Note:
            Thin delegate to :func:`import_analyzer.resolve_relative_import`, the
            single source of truth (#426). Kept as a method so its callers and
            signature are unchanged while the algorithm lives in one place.
        """
        return resolve_relative_import(importer_module, module, level, importer_is_package)

    async def find_importers(
        self, module_path: str, target_file: Path, scope: Scope = "all"
    ) -> Importers:
        """Find project files that import ``module_path`` (reverse import scan).

        Looks the target up in the project's reverse import graph
        (:func:`project_graph.get_import_graph`, #397), built once per
        generation, layout and scope from every file's AST and reused by every
        query. This backs the ``expand(handle, edge="imported_by")`` edge.
        Imports anywhere in a file count, function bodies included (#619).

        The scan is purely AST-based (no Jedi reference resolution), which is
        what gives it breadth: standalone scripts and test files that import the
        target are reported, even when they live outside an importable package
        root.

        Args:
            module_path: Absolute dotted path of the target module.
            target_file: The target module's own file, skipped during the scan
                so a module never reports itself.
            scope: Search scope — "main", "all", or a namespace selector.

        Returns:
            :class:`Importers`. ``named`` holds ``(importer_dotted_module,
            importer_file)`` pairs, deduped by importer module (first occurrence
            wins, in sorted file path order) and sorted by module name.  Files
            are iterated in POSIX-sorted order so "first occurrence wins" is
            deterministic across runs and platforms.  ``unnamed`` holds the
            importing files that have no module name (#668); a relative import
            from such a file can't be anchored, so only its absolute imports
            count.
        """
        root = self.project_path.as_posix()
        # Snapshot before listing files, so a graph built from a listing that a
        # watcher invalidation raced is never cached (#617).
        generation = project_graph.generation(root)
        py_files = sorted(
            await self.get_project_files("*.py", scope),
            key=lambda p: p.as_posix(),
        )
        graph = project_graph.get_import_graph(
            root,
            lambda: self._build_import_graph(py_files),
            generation,
            layout_key=self.layout_key,
            scope_key=_scope_key(scope),
        )

        importers: dict[str, Path] = {}
        unnamed: list[Path] = []
        # Entries are in POSIX-sorted file order, one per file, so "first
        # occurrence wins" is deterministic across runs and platforms.
        for importer, py_file in graph.importers.get(module_path, ()):
            if py_file == target_file:
                continue  # a module never reports itself
            if importer is None:
                unnamed.append(py_file)
            elif importer not in importers:
                importers[importer] = py_file

        return Importers(
            named=[(module, importers[module]) for module in sorted(importers)],
            unnamed=unnamed,
            unparseable=graph.unparseable,
        )

    def _build_import_graph(self, py_files: list[Path]) -> project_graph.ImportGraph:
        """Build the reverse import graph for *py_files* (#397; uncached).

        Inverts the AST match ``find_importers`` used per target: for each file,
        every module it imports is registered with every dotted prefix, so a
        lookup of ``T`` finds exactly the files whose ``import`` names ``T`` or
        a module under it, whose ``from`` clause resolves to ``T`` or below it,
        or that do ``from <pkg> import <name>`` with ``<pkg>.<name> == T``
        (#436; a from-import names a leaf, so that form is exact, never a
        prefix). Relative imports resolve against the importer's module (#343);
        a file with no module name can't anchor one, so only its absolute
        imports count (#668). A file that can't be read or parsed is skipped
        with a warning, as before.

        Args:
            py_files: The files in scope, in POSIX-sorted order.

        Returns:
            The :class:`~pyeye.analyzers.project_graph.ImportGraph`.
        """
        registry: dict[str, list[tuple[str | None, Path]]] = {}
        unparseable: list[str] = []
        for py_file in py_files:
            try:
                importer_module = self._get_import_path_for_file(py_file)
                importer_is_package = py_file.name == "__init__.py"
                tree = _parse_or_record(py_file, unparseable)
                if tree is None:
                    continue
                targets: set[str] = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            targets.update(_dotted_prefixes(alias.name))
                    elif isinstance(node, ast.ImportFrom):
                        if node.level and importer_module is None:
                            continue  # no module to anchor a relative import
                        resolved = self._resolve_relative_import(
                            node.level, node.module, importer_module or "", importer_is_package
                        )
                        if not resolved:
                            continue
                        targets.update(_dotted_prefixes(resolved))
                        targets.update(
                            f"{resolved}.{alias.name}" for alias in node.names if alias.name != "*"
                        )
            except Exception as e:
                logger.warning(f"Could not analyze {py_file} for imports: {e}")
                continue
            for target in targets:
                registry.setdefault(target, []).append((importer_module, py_file))
        return project_graph.ImportGraph(
            importers={target: tuple(entries) for target, entries in registry.items()},
            unparseable=tuple(sorted(unparseable)),
        )

    async def _serialize_name(
        self,
        name: jedi.api.classes.Name,
        include_docstring: bool = False,
    ) -> dict[str, Any]:
        """Serialize a Jedi Name object to a dictionary."""
        result = {
            "name": name.name,
            "type": name.type,
            "line": name.line,
            "column": name.column,
            "description": name.description,
            "full_name": name.full_name,
        }

        if name.module_path:
            result["file"] = Path(name.module_path).as_posix()

        if include_docstring:
            result["docstring"] = name.docstring()

        return result

    # LIVE (not deprecated): the AST class-graph walk backing ``expand(handle,
    # edge="subclasses")``. Expand-only — not in inspect's ``edge_counts`` (#392,
    # direct count gated on #333/#397). Do not remove.
    async def find_subclasses(
        self,
        base_class: str,
        scope: Scope | None = None,
    ) -> dict[str, Any]:
        """Find the classes that inherit *directly* from a given base class.

        **Live, not deprecated.** This is the AST class-graph walk *behind*
        ``expand(handle, edge="subclasses")``; the MCP tool wrapper of the same
        name was removed in v2.0, but this method backs the edge that replaced
        it. ``subclasses`` is expand-only — ``inspect`` does not measure it
        (#392). An earlier docstring marked this for removal in the legacy-tool
        cleanup phase, which would have deleted a live code path.

        Note: the return shape is an ambiguity-aware discriminated union
        (``{"ambiguous": False, "subclasses": [...]}`` vs
        ``{"ambiguous": True, "candidates": [...]}``), introduced to fix a
        name-conflation bug. ``resolve_subclasses`` in ``operations/edges.py``
        depends on that shape.

        Uses a hybrid Jedi + AST approach for performance:
        1. Single-pass AST parsing of scoped files (no double-read)
        2. Builds a parent->children graph (simple-name input) or a resolved
           definition-site index (FQN input)
        3. Uses Jedi Script.goto() to resolve aliased imports

        Direct subclasses only, matching the ``subclasses`` edge (symmetric with
        ``superclasses``). The transitive walk and ``inheritance_chain`` behind
        the old ``include_indirect`` / ``show_hierarchy`` flags had no
        production caller and were removed (#628).

        Determinism ceiling (#419): bases are resolved AST-first
        (:func:`base_resolution.resolve_base` — deterministic) with a Jedi
        forward ``goto`` fallback only when the AST cannot commit (conditional /
        ``TYPE_CHECKING`` imports, externals, dynamic constructs). Forward
        ``goto`` is non-deterministic across fresh processes for some bases, so
        a subclass whose membership hinges on a ``goto``-resolved base can vary
        run-to-run. AST ``import *`` re-export following (#405) keeps the vast
        majority of bases on the deterministic path (~93% AST hits on Django);
        the residual non-determinism is a forward-resolution argument for the
        deterministic backend tracked in #333.

        Args:
            base_class: Name of the base class to find subclasses for
            scope: Search scope (default from smart defaults):
                - "main": Only the main project
                - "all": Main project + configured namespaces
                - "namespace:name": Specific namespace
                - ["main", "namespace:x"]: Multiple scopes
                - None: Use smart default ("all" for this method)

        Returns:
            Discriminated-union dict:
              {"ambiguous": False, "subclasses": [...]}  — unambiguous result
              {"ambiguous": True, "candidates": [...]}   — multiple classes share
                                                           the simple name; caller
                                                           must disambiguate with FQN
        """
        # Determine if the caller supplied a FQN (has a dot) or a bare simple name.
        is_fqn_input = "." in base_class
        # For FQN input the simple leaf name used to match dotted base expressions.
        leaf_name = base_class.split(".")[-1] if is_fqn_input else base_class

        try:
            # Snapshot before listing files, so a graph built from a listing that
            # a watcher invalidation raced is never cached (#617).
            generation = project_graph.generation(self.project_path.as_posix())
            # Get all Python files in scope (cached by get_project_files)
            py_files = await self.get_project_files("*.py", scope, method_name="find_subclasses")

            if is_fqn_input:
                # FQN-strict path (the `subclasses` edge): children whose declared
                # base resolves to the requested FQN's definition site
                # (re-export-aware; #335 Bug A), served from the resolved class
                # graph, built once per generation, layout and scope (#397).
                graph = project_graph.get_class_graph(
                    self.project_path.as_posix(),
                    lambda: self._build_class_graph(py_files),
                    generation,
                    layout_key=self.layout_key,
                    scope_key=_scope_key(scope),
                )
                return {
                    "ambiguous": False,
                    "subclasses": [
                        _subclass_info(fqn, graph.classes[fqn], leaf_name)
                        for fqn in self._direct_children(base_class, graph)
                        if fqn in graph.classes
                    ],
                    "unparseable_files": list(graph.unparseable),  # #729
                }

            # Simple-name path: no production caller (the edge passes a FQN), so
            # it stays uncached and builds its own inventory.
            classes_by_fqn, parent_to_children, _ = self._class_inventory(
                py_files, self._file_to_module(py_files)
            )

            # -------------------------------------------------------------------
            # Ambiguity check: when caller passes a bare simple name and multiple
            # distinct FQN-keyed classes share that leaf name, return the
            # ambiguous variant so the caller can re-call with a FQN.
            # -------------------------------------------------------------------
            matching_fqns_for_name = [
                fqn for fqn in classes_by_fqn if fqn.split(".")[-1] == base_class
            ]
            if len(matching_fqns_for_name) > 1:
                candidates: list[dict[str, Any]] = []
                for fqn in sorted(matching_fqns_for_name):
                    node, _, py_file = classes_by_fqn[fqn]
                    candidates.append(
                        {
                            "handle": fqn,
                            "kind": "class",
                            "location": {
                                "file": py_file.as_posix(),
                                "line_start": node.lineno,
                                "line_end": node.lineno,
                            },
                        }
                    )
                return {"ambiguous": True, "candidates": candidates}

            # Simple name path (unambiguous — ambiguity was checked above).  It
            # uses parent_to_children (+ aliased-base goto) alone and never
            # builds the resolved class graph (#421 item 1).
            direct_fqns: set[str] = set()
            # Check simple name match (e.g., base_class="Animal", class Foo(Animal))
            if base_class in parent_to_children:
                direct_fqns.update(parent_to_children[base_class])

            # Check dotted name matches (e.g., class Foo(module.Animal))
            for parent_name, children in parent_to_children.items():
                if parent_name != base_class and parent_name.endswith(f".{base_class}"):
                    direct_fqns.update(children)

            # Try Jedi-based resolution for aliased imports
            # e.g., "from module import Animal as A" -> class Foo(A)
            direct_fqns.update(
                await self._resolve_aliased_bases(base_class, classes_by_fqn, parent_to_children)
            )

            subclasses: list[dict[str, Any]] = []
            for fqn in direct_fqns:
                if fqn not in classes_by_fqn:
                    continue
                node, _, py_file = classes_by_fqn[fqn]
                subclasses.append(_subclass_info(fqn, _class_fact(node, py_file), leaf_name))

        except Exception as e:
            logger.error(f"Error finding subclasses: {e}")
            raise AnalysisError(
                f"Failed to find subclasses of {base_class}",
                error=str(e),
            ) from e

        return {"ambiguous": False, "subclasses": subclasses}

    def _file_to_module(self, py_files: list[Path]) -> dict[Path, str | None]:
        """Each file's module name, derived ONCE per build and shared (#421 item 3).

        ``None`` means "not importable"; each consumer keeps its own ``stem``
        fallback, so the "same module derivation" invariant holds mechanically.
        """
        return {py_file: self._get_import_path_for_file(py_file) for py_file in py_files}

    def _class_inventory(
        self, py_files: list[Path], file_to_module: dict[Path, str | None]
    ) -> tuple[
        dict[str, tuple[ast.ClassDef, ast.Module, Path]], dict[str, set[str]], tuple[str, ...]
    ]:
        """Every class in *py_files*, plus parent name -> child FQNs (simple-name lookups).

        One pass over each file's cached AST. A file the server's interpreter
        can't parse is recorded (#729); any other failure skips the file, as
        before.

        Returns:
            ``(classes_by_fqn, parent_to_children, unparseable)``: FQN ->
            ``(node, tree, file)``, each declared base's dotted text -> the FQNs
            that name it, and the POSIX-sorted unparseable files.
        """
        classes_by_fqn: dict[str, tuple[ast.ClassDef, ast.Module, Path]] = {}
        parent_to_children: dict[str, set[str]] = {}
        unparseable: list[str] = []
        for py_file in py_files:
            try:
                # Bucket 1: AST comes from cache.
                tree = _parse_or_record(py_file, unparseable)
                if tree is None:
                    continue
                module_path = file_to_module[py_file]
                for node in ast.walk(tree):
                    if not isinstance(node, ast.ClassDef):
                        continue
                    fqn = (
                        f"{module_path}.{node.name}"
                        if module_path
                        else f"{py_file.stem}.{node.name}"
                    )
                    classes_by_fqn[fqn] = (node, tree, py_file)
                    for base in node.bases:
                        parent_name = self._get_base_name_from_ast(base)
                        if parent_name and parent_name != "object":
                            parent_to_children.setdefault(parent_name, set()).add(fqn)
            except Exception as e:
                logger.debug(f"Error parsing {py_file}: {e}")
        return classes_by_fqn, parent_to_children, tuple(sorted(unparseable))

    def _build_class_graph(self, py_files: list[Path]) -> project_graph.ClassGraph:
        """Build the resolved class graph for *py_files* (#397; uncached).

        Resolves each class base ONCE and buckets the child under its base's
        definition-site key (#405). Resolution is AST-first (``resolve_base``: no
        Jedi, #335-robust) with a Jedi ``goto`` fallback only when the AST can't
        commit; both routes yield the same key. Keeps only strings and ints, so
        the cached graph pins no AST, Jedi or parso objects (#713).

        Runs Jedi, so it must run on the analyzer's (Jedi worker) thread.
        """
        file_to_module = self._file_to_module(py_files)
        classes_by_fqn, _, unparseable = self._class_inventory(py_files, file_to_module)
        import_tables, module_defines, star_sources = self._build_ast_resolution_tables(
            py_files, file_to_module
        )
        # Memoised for this build: repeated goto / canonicalisation runs once.
        resolved_cache: dict[tuple[str, int, int], str | None] = {}
        canonical_cache: dict[str, Handle | None] = {}
        children: dict[str, set[str]] = {}
        for child_fqn, (child_node, _, child_file) in classes_by_fqn.items():
            child_module = file_to_module.get(child_file) or child_file.stem
            for base in child_node.bases:
                base_dotted = self._get_base_name_from_ast(base)
                if not base_dotted or base_dotted.split(".")[-1] == "object":
                    continue
                key = self._resolve_base_to_key(
                    base,
                    base_dotted,
                    child_module,
                    child_file,
                    import_tables,
                    module_defines,
                    star_sources,
                    resolved_cache,
                    canonical_cache,
                )
                if key is not None:
                    children.setdefault(key, set()).add(child_fqn)
        return project_graph.ClassGraph(
            classes={
                fqn: _class_fact(node, py_file)
                for fqn, (node, _, py_file) in classes_by_fqn.items()
            },
            children_by_key={key: frozenset(fqns) for key, fqns in children.items()},
            import_tables=import_tables,
            module_defines=module_defines,
            star_sources=star_sources,
            unparseable=unparseable,
        )

    def _direct_children(self, target_fqn: str, graph: project_graph.ClassGraph) -> set[str]:
        """Classes whose base resolves to *target_fqn*'s definition site (or its re-export).

        The target is keyed exactly as bases were (:meth:`_target_index_key`);
        when the AST can't key it, it is canonicalised through the resolver,
        as before (#623).
        """
        key = self._target_index_key(
            target_fqn, graph.import_tables, graph.module_defines, graph.star_sources
        )
        if key is None:
            canon = self._canonical_cached(target_fqn, {})
            key = str(canon) if canon is not None else target_fqn
        return set(graph.children_by_key.get(key, frozenset()))

    def _canonical_cached(
        self, identifier: str, canonical_cache: dict[str, Handle | None]
    ) -> Handle | None:
        """The canonical handle for *identifier*, memoised per ``find_subclasses`` call.

        Canonicalisation goes through the one resolver
        (:func:`pyeye.resolver.resolve_handle`, #623), so a base class is named
        exactly as ``resolve`` / ``inspect`` name it.  It can be repeated many
        times during an indirect-subclass traversal, so results are cached for
        the lifetime of a single ``find_subclasses`` call.  Never raises.
        """
        if identifier not in canonical_cache:
            resolved = resolve_item(identifier, self)  # per base (#704)
            # A Resolved handle is always a valid dotted path (the resolver checks).
            canonical_cache[identifier] = (
                Handle(resolved.handle) if isinstance(resolved, Resolved) else None
            )
        return canonical_cache[identifier]

    def _build_ast_resolution_tables(
        self, py_files: list[Path], file_to_module: dict[Path, str | None]
    ) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]], dict[str, list[str]]]:
        """Build per-module AST import/define/star tables for AST-first resolution (#405).

        Returns ``(import_tables, module_defines, star_sources)`` keyed by the
        same module derivation (:meth:`_get_import_path_for_file`, supplied
        pre-computed via *file_to_module*, #421) used to build class FQNs, so
        resolution keys line up.  ``star_sources`` lets :func:`resolve_base`
        follow ``from x import *`` re-exports (#419 — fewer Jedi ``goto``
        fallbacks, which are the non-deterministic ones).  ASTs come from the
        shared cache; relative imports use the module-level
        :func:`resolve_relative_import` seam (#421).
        """
        import_tables: dict[str, dict[str, str]] = {}
        module_defines: dict[str, dict[str, str]] = {}
        star_sources: dict[str, list[str]] = {}
        for py_file in py_files:
            module_name = file_to_module.get(py_file) or py_file.stem
            if module_name in import_tables:
                continue
            try:
                tree = file_artifact_cache.get_ast(py_file)
            except Exception:
                continue
            is_package = py_file.name == "__init__.py"
            import_tables[module_name] = build_import_table(
                tree, module_name, resolve_relative_import, is_package
            )
            module_defines[module_name] = build_module_defines(tree)
            stars = build_star_sources(tree, module_name, resolve_relative_import, is_package)
            if stars:
                star_sources[module_name] = stars
        return import_tables, module_defines, star_sources

    def _resolve_base_to_key(
        self,
        base: ast.expr,
        base_dotted: str,
        child_module: str,
        child_file: Path,
        import_tables: dict[str, dict[str, str]],
        module_defines: dict[str, dict[str, str]],
        star_sources: dict[str, list[str]],
        resolved_cache: dict[tuple[str, int, int], str | None],
        canonical_cache: dict[str, Handle | None],
    ) -> str | None:
        """Resolve one class base to its definition-site index key, or ``None``.

        AST-first via :func:`resolve_base` (path-independent — this is what
        preserves the old fast-path's macOS-symlink robustness, issue #335;
        ``star_sources`` lets it follow ``import *`` re-exports too, #419).
        Only when the AST cannot commit does it fall back to Jedi ``goto``
        (memoised by source position) plus canonicalisation, exactly as the old
        resolver did across re-export boundaries.  Both routes yield the same
        definition-site string, so index keys are consistent regardless of which
        path resolved a given base.
        """
        ast_resolved = resolve_base(
            child_module, base_dotted, import_tables, module_defines, star_sources
        )
        if ast_resolved is not None:
            return ast_resolved

        leaf_name = base_dotted.split(".")[-1]
        goto_line, goto_col = self._get_ast_leaf_position(base, leaf_name)
        cache_key = (child_file.as_posix(), goto_line, goto_col)
        if cache_key not in resolved_cache:
            resolved_fqn: str | None = None
            try:
                script = file_artifact_cache.get_script(child_file, self.project)
                # ``goto`` is already aimed at the base's leaf token via
                # ``_get_ast_leaf_position``, so the first result carrying a
                # ``full_name`` IS the resolved base.  Do NOT gate on
                # ``gr.name == leaf_name``: for an aliased base (``class X(A)``
                # where ``A`` aliases ``Animal``) Jedi returns the *resolved*
                # name (``Animal``), not the alias, so that gate silently drops
                # the subclass when the alias isn't statically followable
                # (e.g. a try/except / TYPE_CHECKING import — #420 review #1).
                for gr in script.goto(goto_line, goto_col, follow_imports=True):
                    if gr.full_name:
                        resolved_fqn = gr.full_name
                        break
            except Exception:
                resolved_fqn = None
            resolved_cache[cache_key] = resolved_fqn

        resolved = resolved_cache[cache_key]
        if resolved is None:
            return None
        canonical = self._canonical_cached(resolved, canonical_cache)
        return str(canonical) if canonical is not None else resolved

    def _target_index_key(
        self,
        target_fqn: str,
        import_tables: dict[str, dict[str, str]],
        module_defines: dict[str, dict[str, str]],
        star_sources: dict[str, list[str]],
    ) -> str | None:
        """Resolve a target FQN to its AST definition-site key, or ``None``.

        Splits the FQN into ``module.leaf`` and reuses :func:`resolve_base`, so a
        target is keyed the same way bases are (following re-exports, including
        ``import *``, via AST).  ``None`` means the AST cannot resolve it — the
        caller then falls back to Jedi canonicalisation to stay byte-identical
        with the old re-export match.
        """
        if "." not in target_fqn:
            return None
        target_module, target_leaf = target_fqn.rsplit(".", 1)
        return resolve_base(target_module, target_leaf, import_tables, module_defines, star_sources)

    async def _resolve_aliased_bases(
        self,
        base_class: str,
        classes_by_fqn: dict[str, tuple[ast.ClassDef, ast.Module, Path]],
        parent_to_children: dict[str, set[str]],
    ) -> set[str]:
        """Resolve aliased base references for the **simple-name** seed path.

        Handles ``from module import Animal as A; class Foo(A):`` where AST
        simple-name matching alone would miss the relationship: any class whose
        aliased base goto-resolves to a definition named ``base_class`` is
        included.  This is the only mode left — the FQN path's resolved index
        (#405) already handles FQN-strict aliasing, so the former
        ``target_fqn``/canonical-match mode (and ``_fqn_matches_target``) was
        removed as dead code (#420 review #2).

        Args:
            base_class: The simple name (leaf) of the base class to match.
            classes_by_fqn: FQN -> (node, tree, file) mapping.
            parent_to_children: parent name -> set of child FQNs.
        """
        resolved_fqns: set[str] = set()

        # Only check parent names that didn't match base_class by simple name —
        # these are the aliased-import candidates.
        candidate_parents = {
            name
            for name in parent_to_children
            if name != base_class and not name.endswith(f".{base_class}")
        }
        if not candidate_parents:
            return resolved_fqns

        # Group classes by file to minimize Jedi Script creation
        file_to_classes: dict[str, list[tuple[str, ast.ClassDef]]] = {}
        for fqn, (node, _, py_file) in classes_by_fqn.items():
            file_key = py_file.as_posix()
            for base in node.bases:
                parent_name = self._get_base_name_from_ast(base)
                if parent_name in candidate_parents:
                    file_to_classes.setdefault(file_key, []).append((fqn, node))
                    break

        for file_path_str, class_entries in file_to_classes.items():
            try:
                file_path = Path(file_path_str)
                # Bucket 1: analysis input — Script comes from cache.
                script = file_artifact_cache.get_script(file_path, self.project)

                for fqn, node in class_entries:
                    for base in node.bases:
                        parent_name = self._get_base_name_from_ast(base)
                        if parent_name not in candidate_parents:
                            continue

                        # goto() resolves what this base name points to; include
                        # the child when it resolves to a definition named base_class.
                        try:
                            for result in script.goto(
                                base.lineno, base.col_offset, follow_imports=True
                            ):
                                if result.name == base_class:
                                    resolved_fqns.add(fqn)
                                    break
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"Error resolving aliases in {file_path_str}: {e}")

        return resolved_fqns

    @staticmethod
    def _get_ast_leaf_position(base: Any, leaf_name: str) -> tuple[int, int]:
        """Get the source position of the leaf name in a base class AST node.

        For a simple ``ast.Name`` node the col_offset already points at the name.
        For an ``ast.Attribute`` chain like ``_core.widgets.Widget`` the node's
        col_offset points at the first component (``_core``), while Jedi needs
        to be positioned at ``Widget`` to follow imports to the class definition.

        Uses ``end_col_offset`` (present in Python 3.8+) to compute where the
        final attribute name starts.
        """
        if isinstance(base, ast.Attribute) and base.attr == leaf_name:
            end_col = getattr(base, "end_col_offset", None)
            if end_col is not None:
                return base.lineno, end_col - len(leaf_name)
        return base.lineno, base.col_offset

    @staticmethod
    def _get_base_name_from_ast(base: Any) -> str | None:
        """Extract the name from an AST base class node."""
        if isinstance(base, ast.Name):
            return base.id
        elif isinstance(base, ast.Attribute):
            parts = []
            node: Any = base
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value
            if isinstance(node, ast.Name):
                parts.append(node.id)
            return ".".join(reversed(parts))
        return None
