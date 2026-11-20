"""Configuration management for PyEye."""

import copy
import json
import logging
import os
from pathlib import Path
from typing import Any

from .constants import CONFIG_FILE, CONFIG_FILES, GLOBAL_CONFIG_FILES, OVERRIDE_FILE, PROJECT_NAME
from .path_utils import normalize_path, path_to_key
from .project_layout import detect_src_layout
from .validation import PathValidator, ValidationError

logger = logging.getLogger(__name__)

#: The ``reason`` of a config entry the path check refused (#898), as distinct
#: from a ``package:`` path that merely doesn't exist (#842).
REJECTED_PATH = "rejected_path"

#: Session-only config additions per project, from ``configure_packages(save=False)``
#: (#953), keyed by :func:`path_to_key` of the resolved project path. Applied over
#: the disk sources by every :class:`ProjectConfig` load, so successive unsaved
#: calls accumulate as documented, and cleared by a save that persists them. It
#: lives as long as the server process: unsaved entries last until restart or a save.
_UNSAVED: dict[str, dict[str, Any]] = {}


def _unsaved_key(project_path: str | Path) -> str:
    return path_to_key(normalize_path(project_path))


def _posix_entry(entry: str | Path) -> str:
    """A config entry in POSIX spelling, as the config and responses carry paths (#717).

    ``Path`` reads the platform's separators, so a Windows backslash becomes
    ``/`` while a POSIX name that merely contains one is left alone.
    """
    return Path(entry).as_posix()


def add_unsaved(
    project_path: str | Path,
    packages: list[str] | None = None,
    namespaces: dict[str, list[str]] | None = None,
    standalone_dirs: list[str] | None = None,
) -> None:
    """Record unsaved config entries for *project_path*, merged as a save would merge them.

    Packages and standalone dirs extend, deduped; a namespace replaces that
    namespace's list, as ``configure_packages(save=True)`` does (#953).
    """
    overlay = _UNSAVED.setdefault(
        _unsaved_key(project_path), {"packages": [], "namespaces": {}, "standalone_dirs": []}
    )
    overlay["packages"] = list(
        dict.fromkeys([*overlay["packages"], *map(_posix_entry, packages or [])])
    )
    overlay["namespaces"].update(
        {ns: [_posix_entry(p) for p in paths] for ns, paths in (namespaces or {}).items()}
    )
    overlay["standalone_dirs"] = list(
        dict.fromkeys([*overlay["standalone_dirs"], *map(_posix_entry, standalone_dirs or [])])
    )


def has_unsaved(project_path: str | Path) -> bool:
    """Whether *project_path* has unsaved config entries (#953)."""
    overlay = _UNSAVED.get(_unsaved_key(project_path))
    return bool(overlay and any(overlay.values()))


def clear_unsaved(project_path: str | Path) -> None:
    """Forget *project_path*'s unsaved entries, once a save has persisted them (#953)."""
    _UNSAVED.pop(_unsaved_key(project_path), None)


#: The top-level keys of the pyeye config that pyeye reads (docs facts
#: ``config.key.*``). ``tests/test_docs_facts_repo_config.py`` fails if code reads
#: a top-level key that isn't listed here.
CONFIG_KEYS: tuple[str, ...] = (
    "packages",
    "namespaces",
    "standalone",
    "scope_defaults",
    "scope_aliases",
    "environment",
)

#: Top-level config keys that docs or the generated example once described,
#: but that nothing in pyeye has ever read (#581). They are ignored with a
#: warning instead of reading as live settings.
IGNORED_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "analysis",
    "cache",
    "default_packages",
    "exclude",
    "exclude_patterns",
    "logging",
    "performance",
    "plugins",
    "watch_exclude",
)


class ProjectConfig:
    """Manages project-specific configuration for code intelligence."""

    # Config file names to check (in order of precedence)
    CONFIG_FILES = CONFIG_FILES

    def __init__(self, project_path: str = ".", *, include_unsaved: bool = True) -> None:
        """Initialize configuration for a project.

        Args:
            project_path: Root path of the project
            include_unsaved: Apply the session's unsaved additions (#953).
                ``False`` gives the configuration as the disk sources alone
                describe it, to tell what is unsaved.
        """
        self.project_path = normalize_path(project_path)
        self.include_unsaved = include_unsaved
        self.config: dict[str, Any] = {}
        self.has_explicit_config: bool = False
        #: Config sources that failed to load, as ``"<path>: <error>"`` (#898):
        #: their entries are unknown, so :meth:`rejected_paths` can't vouch for them.
        self.load_errors: list[str] = []
        #: The project config file's OWN content (its pyeye section), plus the
        #: explicit additions made since: what a save writes (#1038). Never the
        #: global config, the override file or a derived package.
        self._project_layer: dict[str, Any] = {}
        #: Packages pyeye added on its own, as ``(entry, reason)`` in the
        #: config's own spelling; see :meth:`discovered` (#1038).
        self._derived: list[tuple[str, str]] = []
        self.load_config()

    def load_config(self) -> None:
        """Load configuration from various sources.

        Loading order (later sources override earlier ones):
        1. Global config (~/.config/pyeye/config.json)
        2. Project config files (.pyeye.json, pyproject.toml, etc.)
        3. Override file (.pyeye.override.json) - for local development
        4. Auto-discovery (if no packages configured)
        5. The session's unsaved additions (``configure_packages(save=False)``,
           #953), last, as a ``save=False`` call appended them before: they
           don't suppress auto-discovery
        """
        # 1. Load global config first (lowest precedence)
        self._load_global_config()

        # 2. Load project config files
        for config_file in self.CONFIG_FILES:
            config_path = self.project_path / config_file
            if config_path.exists():
                self._load_from_file(config_path, project_file=True)
                self.has_explicit_config = True
                break

        # 3. Load override file (highest precedence)
        override_path = self.project_path / OVERRIDE_FILE
        if override_path.exists():
            self._load_from_file(override_path)
            self.has_explicit_config = True

        # 4. Auto-discover if no config found
        if not self.config.get("packages"):
            self._auto_discover()

        # 5. The session's unsaved additions (#953), merged as a save merges them.
        if self.include_unsaved:
            self._apply_unsaved()

        ignored = self.get_ignored_top_level_keys()
        if ignored:
            logger.warning(self.ignored_top_level_keys_message(ignored))

    def _apply_unsaved(self) -> None:
        """Merge this project's unsaved entries over the loaded config (#953).

        Into the project layer too: a save persists them (#953, #1038).
        """
        overlay = _UNSAVED.get(_unsaved_key(self.project_path))
        if not overlay:
            return
        self.add_explicit(overlay["packages"], overlay["namespaces"], overlay["standalone_dirs"])

    def add_explicit(
        self,
        packages: list[str] | None = None,
        namespaces: dict[str, list[str]] | None = None,
        standalone_dirs: list[str] | None = None,
    ) -> None:
        """Add explicit entries (a ``configure_packages`` call's, the session's unsaved).

        They go into the merged config AND the project layer, so a save
        writes them (#1038). Packages and standalone dirs extend, deduped by
        POSIX spelling; a namespace replaces its list (#953).
        """
        for target in (self.config, self._project_layer):
            if packages:
                existing = target.setdefault("packages", [])
                have = {_posix_entry(p) for p in existing}
                existing.extend(_posix_entry(p) for p in packages if _posix_entry(p) not in have)
            if namespaces:
                target.setdefault("namespaces", {}).update(
                    {ns: [_posix_entry(p) for p in paths] for ns, paths in namespaces.items()}
                )
            if standalone_dirs:
                if not isinstance(target.get("standalone"), dict):
                    target["standalone"] = {}
                dirs = target["standalone"].setdefault("dirs", [])
                have = {_posix_entry(d) for d in dirs}
                dirs.extend(_posix_entry(d) for d in standalone_dirs if _posix_entry(d) not in have)

    def discovered(self) -> list[dict[str, str]]:
        """The packages pyeye added on its own, each with why (#1038).

        ``reason`` is ``sibling``, ``src_layout``, ``pyright_extra_paths`` or
        ``build_backend_layout``. ``path`` is resolved and POSIX, the form
        ``packages`` reports. ``[]`` when none were added, e.g. once
        ``packages`` are configured. They are analysed, but never saved.
        """
        out = []
        for entry, reason in self._derived:
            path = Path(entry).expanduser()
            if not path.is_absolute():
                path = self.project_path / path
            out.append({"path": normalize_path(path).as_posix(), "reason": reason})
        return out

    def get_ignored_top_level_keys(self) -> list[str]:
        """Return the (sorted) top-level keys in the config that pyeye ignores (#581)."""
        return sorted(key for key in IGNORED_TOP_LEVEL_KEYS if key in self.config)

    @staticmethod
    def ignored_top_level_keys_message(keys: list[str]) -> str:
        """Explain that the top-level config *keys* have no effect."""
        names = ", ".join(keys)
        return (
            f"Ignoring {names} in the {PROJECT_NAME} config: {PROJECT_NAME} has never "
            "read these keys, so they have no effect (#581). Remove them to silence "
            "this warning."
        )

    def _load_from_file(self, config_path: Path, *, project_file: bool = False) -> None:
        """Load configuration from a file.

        With *project_file*, its pyeye section is also kept as the project
        layer, the base of what a save writes (#1038).
        """
        logger.info(f"Loading config from {config_path.as_posix()}")

        try:
            if config_path.suffix == ".json":
                with open(config_path) as f:
                    data = json.load(f)
                    section = data.get(PROJECT_NAME, data)
                    self.config.update(section)
                    if project_file:
                        self._project_layer = copy.deepcopy(section)

            elif config_path.suffix in [".yaml", ".yml"]:
                with open(config_path) as f:
                    import yaml

                    data = yaml.safe_load(f)
                    section = data.get(PROJECT_NAME, data)
                    self.config.update(section)
                    if project_file:
                        self._project_layer = copy.deepcopy(section)

            elif config_path.name == "pyproject.toml":
                import tomllib

                with open(config_path, "rb") as f:
                    data = tomllib.load(f)

                    # Read PyEye-specific config first
                    if "tool" in data and PROJECT_NAME in data["tool"]:
                        self.config.update(data["tool"][PROJECT_NAME])
                        if project_file:
                            self._project_layer = copy.deepcopy(data["tool"][PROJECT_NAME])

                    # Read [tool.pyright] extraPaths — projects already declare
                    # their dependencies here, no need for duplicate .pyeye.json
                    self._read_pyright_extra_paths(data)

                    # Auto-detect source layouts from build backend metadata
                    # Only apply if no packages already configured
                    if not self.config.get("packages"):
                        self._detect_source_layout(data)

        except Exception as e:
            logger.error(f"Error loading config from {config_path.as_posix()}: {e}")
            self.load_errors.append(f"{config_path.as_posix()}: {e}")

    def _load_global_config(self) -> None:
        """Load global configuration from user home.

        Global config provides defaults that can be overridden by project config.
        """
        global_configs = [Path.home() / name for name in GLOBAL_CONFIG_FILES]

        for config_path in global_configs:
            if config_path.exists():
                try:
                    with open(config_path) as f:
                        global_config = json.load(f)
                        # Global config loaded first, so just update
                        self.config.update(global_config)
                        logger.info(f"Loaded global config from {config_path.as_posix()}")
                        break
                except Exception as e:
                    logger.error(f"Error loading global config: {e}")
                    self.load_errors.append(f"{config_path.as_posix()}: {e}")

    def _detect_setuptools_layout(self, tool_config: dict[str, Any]) -> list[str]:
        """Extract setuptools [tool.setuptools.packages.find.where].

        Args:
            tool_config: The [tool] section from pyproject.toml

        Returns:
            List of detected paths
        """
        paths = []
        if "setuptools" in tool_config:
            setuptools_config = tool_config["setuptools"]
            if "packages" in setuptools_config:
                packages_config = setuptools_config["packages"]
                if "find" in packages_config:
                    where = packages_config["find"].get("where", [])
                    if isinstance(where, list):
                        paths.extend(where)
                    elif isinstance(where, str):
                        paths.append(where)
        return paths

    def _detect_poetry_layout(self, tool_config: dict[str, Any]) -> list[str]:
        """Extract poetry [tool.poetry.packages].

        Args:
            tool_config: The [tool] section from pyproject.toml

        Returns:
            List of detected paths
        """
        paths = []
        if "poetry" in tool_config:
            poetry_config = tool_config["poetry"]
            if "packages" in poetry_config:
                for package in poetry_config["packages"]:
                    if "from" in package:
                        paths.append(package["from"])
        return paths

    def _detect_hatch_layout(self, tool_config: dict[str, Any]) -> list[str]:
        """Extract hatch [tool.hatch.build.targets.wheel.sources].

        Args:
            tool_config: The [tool] section from pyproject.toml

        Returns:
            List of detected paths
        """
        paths = []
        if "hatch" in tool_config:
            hatch_config = tool_config["hatch"]
            if "build" in hatch_config:
                build_config = hatch_config["build"]
                if "targets" in build_config and "wheel" in build_config["targets"]:
                    wheel_config = build_config["targets"]["wheel"]
                    if "sources" in wheel_config:
                        sources = wheel_config["sources"]
                        if isinstance(sources, list):
                            paths.extend(sources)
                        elif isinstance(sources, str):
                            paths.append(sources)
        return paths

    def _detect_pdm_layout(self, tool_config: dict[str, Any]) -> list[str]:
        """Extract PDM [tool.pdm.build.package-dir].

        Args:
            tool_config: The [tool] section from pyproject.toml

        Returns:
            List of detected paths
        """
        paths = []
        if "pdm" in tool_config:
            pdm_config = tool_config["pdm"]
            if "build" in pdm_config:
                build_config = pdm_config["build"]
                if "package-dir" in build_config:
                    paths.append(build_config["package-dir"])
        return paths

    def _add_detected_paths(self, detected_paths: list[str]) -> None:
        """Validate and add detected paths to config.

        Args:
            detected_paths: List of paths detected from build backend metadata
        """
        if not detected_paths:
            return

        valid_paths = []
        for path in detected_paths:
            full_path = self.project_path / path
            if full_path.exists() and full_path.is_dir():
                valid_paths.append(path)

        if valid_paths:
            self.config.setdefault("packages", []).extend(valid_paths)
            self._derived.extend((p, "build_backend_layout") for p in valid_paths)
            logger.info(f"Auto-detected source layout from pyproject.toml: {valid_paths}")

    def _read_pyright_extra_paths(self, pyproject_data: dict[str, Any]) -> None:
        """Read extra paths from [tool.pyright] in pyproject.toml.

        Projects often declare their cross-package dependencies in pyright's
        ``executionEnvironments[*].extraPaths``.  These are the same paths
        pyeye needs to resolve symbols across packages, so we read them
        instead of requiring a separate ``.pyeye.json``.

        Also reads the top-level ``[tool.pyright].extraPaths`` which is the
        simpler single-environment form.

        Args:
            pyproject_data: Parsed pyproject.toml data.
        """
        if "tool" not in pyproject_data or "pyright" not in pyproject_data["tool"]:
            return

        pyright = pyproject_data["tool"]["pyright"]
        extra_paths: list[str] = []

        # Top-level extraPaths (simple form)
        if "extraPaths" in pyright and isinstance(pyright["extraPaths"], list):
            extra_paths.extend(pyright["extraPaths"])

        # executionEnvironments[*].extraPaths (multi-environment form)
        if "executionEnvironments" in pyright and isinstance(
            pyright["executionEnvironments"], list
        ):
            for env in pyright["executionEnvironments"]:
                if isinstance(env, dict) and "extraPaths" in env:
                    for p in env["extraPaths"]:
                        if p not in extra_paths:
                            extra_paths.append(p)

        if not extra_paths:
            return

        # Resolve relative paths and add as packages
        resolved = []
        for p in extra_paths:
            path = Path(p)
            if not path.is_absolute():
                path = self.project_path / path
            path = normalize_path(path)
            if path.exists() and path.as_posix() not in resolved:
                resolved.append(path.as_posix())

        if resolved:
            self.config.setdefault("packages", []).extend(resolved)
            self._derived.extend((p, "pyright_extra_paths") for p in resolved)
            self.has_explicit_config = True
            logger.info(f"Read {len(resolved)} extra paths from [tool.pyright]: {resolved}")

    def _detect_source_layout(self, pyproject_data: dict[str, Any]) -> None:
        """Detect source layout from pyproject.toml build backend metadata.

        Supports multiple build backends:
        - setuptools: [tool.setuptools.packages.find.where]
        - poetry: [tool.poetry.packages]
        - hatch: [tool.hatch.build.targets.wheel.sources]
        - pdm: [tool.pdm.build.package-dir]

        Args:
            pyproject_data: Parsed pyproject.toml data
        """
        if "tool" not in pyproject_data:
            return

        tool_config = pyproject_data["tool"]
        detected_paths: list[str] = []

        # Delegate to specialized methods
        detected_paths.extend(self._detect_setuptools_layout(tool_config))
        detected_paths.extend(self._detect_poetry_layout(tool_config))
        detected_paths.extend(self._detect_hatch_layout(tool_config))
        detected_paths.extend(self._detect_pdm_layout(tool_config))

        self._add_detected_paths(detected_paths)

    def _discover_src_layout(self) -> bool:
        """Check for src/ layout and add if found.

        Returns:
            True if src/ layout was found and added, False otherwise
        """
        if detect_src_layout(self.project_path) is not None:
            self.config.setdefault("packages", []).append("src")
            self._derived.append(("src", "src_layout"))
            logger.info("Auto-detected source layout: src/")
            return True
        return False

    def _discover_sibling_packages(self) -> list[str]:
        """Discover sibling packages in parent directory.

        Returns:
            List of sibling package paths
        """
        potential_packages = []
        parent = self.project_path.parent

        if parent != self.project_path:
            try:
                # Sorted: iterdir order varies by filesystem, and the packages'
                # order is Jedi's root order (#1038).
                for sibling in sorted(parent.iterdir()):
                    try:
                        if (
                            sibling.is_dir()
                            and sibling != self.project_path
                            and (any(sibling.glob("*.py")) or (sibling / "setup.py").exists())
                        ):
                            potential_packages.append(str(sibling))
                    except (PermissionError, OSError):
                        continue
            except (PermissionError, OSError):
                pass

        return potential_packages

    def _auto_discover(self) -> None:
        """Auto-discover package locations."""
        # Check for src layout first (most specific pattern)
        if self._discover_src_layout():
            return  # Don't look for other patterns if src/ found

        # Discover sibling packages. The project's virtualenv is not a package:
        # its site-packages reach Jedi as the project environment, for every
        # layout, src/ included (pyeye.environment, #993).
        potential_packages = []
        potential_packages.extend(self._discover_sibling_packages())

        if potential_packages:
            logger.info(f"Auto-discovered packages: {potential_packages}")
            self.config.setdefault("packages", []).extend(potential_packages)
            self._derived.extend((p, "sibling") for p in potential_packages)

    def _process_package_path(self, package: str) -> list[str]:
        """Process a single package path, handling globs and validation.

        Args:
            package: Package path (may contain glob patterns)

        Returns:
            List of validated paths
        """
        try:
            # The one rule shared with namespaces (#668): ``~`` expanded,
            # relative to the project, ``..`` collapsed.
            package = self._normalise_config_path(package)
            return self._checked_package_dirs(package)
        except ValidationError as e:
            logger.warning(f"Skipping invalid package path {package}: {e}")
            return []

    @staticmethod
    def _expand_glob(normalised: str) -> list[str]:
        """The directories a normalised config entry names: a glob's matches, or itself (#872).

        The ONE expansion, for packages and namespaces alike, so the two can't
        disagree again. Matches are sorted: a namespace's order is its
        precedence (first portion wins, #419), and ``glob`` returns them in
        filesystem order. Only ``*`` makes a glob, so a literal path containing
        ``?`` or ``[`` keeps its meaning. ``configure_packages``' check treats
        ``*?[`` as glob (``mcp.server._config_entry_targets``): checking more
        entries by their matches than are expanded is only stricter.
        """
        if "*" not in normalised:
            return [normalised]
        from glob import glob

        return sorted(Path(match).as_posix() for match in glob(normalised))

    def _checked_package_dirs(self, normalised: str) -> list[str]:
        """A normalised package entry's directories, each checked as a scan root.

        A glob gives its matches; a plain entry, itself if it exists. The one
        check of a package-path entry, for the getters and :meth:`rejected_paths`
        alike (#898).

        Raises:
            ValidationError: For the first directory the path check refuses, so
                a glob with a refused match is skipped whole, never in part.
        """
        is_glob = "*" in normalised
        paths = []
        for target in self._expand_glob(normalised):
            validated = PathValidator.validate_path(target)
            # A directory to scan: not "/" (or another ancestor of /etc) either.
            PathValidator.validate_scan_root(target, self.project_path)
            if is_glob or validated.exists():
                paths.append(validated.as_posix())
        return paths

    def _process_namespace_paths(self, namespaces: dict[str, list[str]]) -> list[str]:
        """Process namespace paths, handling globs and validation.

        Args:
            namespaces: Dictionary mapping namespace to paths

        Returns:
            List of validated paths
        """
        paths = []
        for _namespace, ns_paths in namespaces.items():
            for ns_path in ns_paths:
                try:
                    ns_path = self._normalise_config_path(ns_path)
                    paths.extend(self._checked_package_dirs(ns_path))
                except ValidationError as e:
                    logger.warning(
                        f"Skipping invalid namespace path {Path(ns_path).as_posix()}: {e}"
                    )

        return paths

    def _deduplicate_paths(self, paths: list[str]) -> list[str]:
        """Remove duplicate paths while preserving order.

        Args:
            paths: List of paths (may contain duplicates)

        Returns:
            List of unique paths in original order
        """
        seen = set()
        unique_paths: list[str] = []
        for path in paths:
            path_str = Path(path).as_posix()
            if path_str not in seen:
                seen.add(path_str)
                unique_paths.append(path_str)

        return unique_paths

    def get_package_paths(self) -> list[str]:
        """Get all configured package paths.

        Returns:
            List of absolute paths to packages
        """
        paths = []

        # Add configured packages
        for package in self.config.get("packages", []):
            paths.extend(self._process_package_path(package))

        # Add namespace paths
        namespaces = self.config.get("namespaces", {})
        paths.extend(self._process_namespace_paths(namespaces))

        # Always include current project
        paths.insert(0, self.project_path.as_posix())

        # Remove duplicates while preserving order
        return self._deduplicate_paths(paths)

    def get_namespaces(self) -> dict[str, list[str]]:
        """Get configured namespace packages.

        Returns:
            Dictionary mapping namespace to paths
        """
        namespaces = self.config.get("namespaces", {})
        if not namespaces:
            return {}
        # #668/#669: this is the one source every consumer reads (ProjectManager,
        # plugins, configure_packages), so paths are normalised HERE, the same
        # way package paths are: relative to the project, ``~`` expanded, ``..``
        # collapsed.  A raw "../repo" was resolved differently by each consumer
        # (or against the server's CWD), and "app/../repo" defeated the
        # file<->module mapper.
        # A glob entry expands to its sorted matches, through the helper the
        # package paths use (#872). A namespace whose entries match nothing keeps
        # its key with no directories: still configured, so its scope is
        # reported unsearched, never silently absent (#842).
        return {
            ns: list(dict.fromkeys(d for p in paths for d in self._namespace_dirs(p, ns)))
            for ns, paths in namespaces.items()
        }

    def _namespace_dirs(self, entry: str, namespace: str) -> list[str]:
        """The checked directories of one namespace *entry*; ``[]`` if any is refused (#856)."""
        refusal = self._namespace_refusal(entry)
        if refusal is not None:
            logger.warning(f"Skipping config path {entry} ({namespace}): {refusal}")
            return []
        return self._expand_glob(self._normalise_config_path(entry))

    def _namespace_refusal(self, entry: str) -> str | None:
        """Why :meth:`get_namespaces` skips namespace *entry*, or ``None`` (#856, #872, #898).

        The first refused directory the entry names (a glob's matches, #872);
        the one check, for the getter and :meth:`rejected_paths` alike.
        """
        for target in self._expand_glob(self._normalise_config_path(entry)):
            if (refusal := self._path_refusal(target)) is not None:
                return refusal
        return None

    def _passes_path_check(self, entry: str, what: str) -> bool:
        """Whether a config path *entry* passes the input check in its final form (#856).

        A refused entry is skipped with a warning, as package paths already are,
        never an error: a bad ``.pyeye.json`` must not break every call.
        """
        refusal = self._path_refusal(entry)
        if refusal is not None:
            logger.warning(f"Skipping config path {entry} ({what}): {refusal}")
            return False
        return True

    def _path_refusal(self, entry: str) -> str | None:
        """Why the path check refuses directory *entry* (normalised), or ``None`` (#856, #898)."""
        try:
            # A directory to scan: an ancestor of a restricted one is refused too.
            PathValidator.validate_scan_root(entry, self.project_path)
        except ValidationError as error:
            return str(error)
        return None

    def rejected_paths(self) -> list[dict[str, str]] | None:
        """Every config path entry the path check refuses, for the caller to see (#898).

        The getters skip a refused entry with a warning (#856); this reports the
        same entries, through the same checks, so a result can't silently omit a
        package the user configured (#568). One record per refused entry:
        ``{scope, path, reason: "rejected_path", detail}``, where ``scope`` is the
        scope it belongs to (``packages``, ``namespace:<name>`` or
        ``standalone``) and ``path`` is the entry as written. ``[]`` when none.

        ``None`` when the check can't be complete: a config source failed to
        load (:attr:`load_errors`), so its entries were never seen. ``[]`` is
        always a measured "none refused", never a check that didn't finish.
        """
        if self.load_errors:
            return None
        rejected: list[dict[str, str]] = []

        def record(scope: str, raw: str, detail: str | None) -> None:
            if detail is not None:
                rejected.append(
                    {"scope": scope, "path": raw, "reason": REJECTED_PATH, "detail": detail}
                )

        for raw in self.config.get("packages", []):
            record("packages", raw, self._package_refusal(raw))
        for ns, raws in (self.config.get("namespaces") or {}).items():
            for raw in raws:
                # get_namespaces and get_package_paths each check its directories.
                record(
                    f"namespace:{ns}",
                    raw,
                    self._namespace_refusal(raw) or self._package_refusal(raw),
                )
        for raw in self.get_standalone_config().get("dirs", []):
            record("standalone", raw, self._path_refusal(self._standalone_dir(raw).as_posix()))
        return rejected

    def _package_refusal(self, raw: str) -> str | None:
        """Why :meth:`_process_package_path` skips package entry *raw*, or ``None``."""
        try:
            self._checked_package_dirs(self._normalise_config_path(raw))
        except ValidationError as error:
            return str(error)
        return None

    def _normalise_config_path(self, entry: str) -> str:
        """Return *entry* as an absolute, normalised POSIX path.

        Relative entries are taken relative to the project directory, as
        package paths are; ``~`` is expanded and ``..`` collapsed.  Glob
        patterns are returned with only that anchoring applied; callers that
        need the matches expand them.
        """
        path = Path(os.path.expanduser(entry))
        if not path.is_absolute():
            path = self.project_path / path
        if "*" in entry:
            return path.as_posix()
        return path_to_key(path)

    def get_scope_defaults(self) -> dict[str, Any]:
        """Get configured scope defaults.

        Returns:
            Dictionary with global and method-specific scope defaults
        """
        defaults = self.config.get("scope_defaults", {})
        return dict(defaults) if defaults else {}

    def get_scope_aliases(self) -> dict[str, Any]:
        """Get configured scope aliases.

        Returns:
            Dictionary mapping alias names to scope specifications
        """
        aliases = self.config.get("scope_aliases", {})
        return dict(aliases) if aliases else {}

    def _standalone_dir(self, dir_path: str) -> Path:
        """A ``standalone.dirs`` entry as the config uses it: ``~`` expanded, on the project."""
        resolved_path = Path(dir_path).expanduser()
        if not resolved_path.is_absolute():
            resolved_path = self.project_path / resolved_path
        return resolved_path

    def get_standalone_paths(self) -> list[Path]:
        """The configured standalone script directories that exist (#690).

        Relative entries are taken from the project root. The one source for
        the analyzer (via ``ProjectManager``) and the plugins.
        """
        paths: list[Path] = []
        for dir_path in self.get_standalone_config().get("dirs", []):
            resolved_path = self._standalone_dir(dir_path)
            if not self._passes_path_check(resolved_path.as_posix(), "standalone.dirs"):
                continue
            if resolved_path.exists():
                paths.append(resolved_path)
            else:
                logger.warning(f"Standalone directory does not exist: {resolved_path.as_posix()}")
        return paths

    def get_environment_setting(self) -> str | bool | None:
        """The ``environment`` setting (#993): a virtualenv path, ``False`` to opt out, or ``None``.

        Read by :func:`pyeye.environment.discover`, which path-checks it.
        """
        value = self.config.get("environment")
        if value is None or value is False or isinstance(value, str):
            return value
        logger.warning(f"Ignoring environment {value!r}: expected a path or false")
        return None

    def get_standalone_config(self) -> dict[str, Any]:
        """Get standalone scripts configuration.

        Returns:
            ``{"dirs": [...]}`` — the directories of standalone scripts. Every
            ``.py`` file under them is analysed.

        Any other key under ``standalone`` is ignored: ``recursive``,
        ``file_pattern`` and ``exclude_patterns`` were removed in 2.0 because
        nothing ever applied them (#513). See :meth:`get_ignored_standalone_keys`.
        """
        standalone = self.config.get("standalone") or {}
        ignored = self.get_ignored_standalone_keys()
        if ignored:
            logger.warning(self.ignored_standalone_keys_message(ignored))
        return {"dirs": list(standalone.get("dirs", []))}

    def get_ignored_standalone_keys(self) -> list[str]:
        """Return the (sorted) keys under ``standalone`` that are ignored."""
        standalone = self.config.get("standalone") or {}
        return sorted(key for key in standalone if key != "dirs")

    @staticmethod
    def ignored_standalone_keys_message(keys: list[str]) -> str:
        """Explain that *keys* under ``standalone`` in the config are ignored."""
        names = ", ".join(f"standalone.{key}" for key in keys)
        return (
            f"Ignoring {names} in the {PROJECT_NAME} config: standalone directories "
            "are scanned in full, and these options were removed in 2.0 because "
            "they never took effect (#513). Remove them to silence this warning."
        )

    def save_config(self, config_path: Path | None = None) -> None:
        """Save current configuration to a file.

        Args:
            config_path: Path to save to (defaults to .pyeye.json)
        """
        if config_path is None:
            config_path = self.project_path / CONFIG_FILE

        try:
            # The project's own config and its explicit additions only (#1038):
            # never a derived package, the global config or the override file.
            with open(config_path, "w") as f:
                json.dump(self._project_layer, f, indent=2)
            logger.info(f"Saved config to {config_path.as_posix()}")
        except Exception as e:
            logger.error(f"Error saving config: {e}")


def create_example_config(project_path: str = ".") -> None:
    """Create an example configuration file.

    Args:
        project_path: Where to create the config
    """
    example = {
        "packages": [
            ".",
            "../my-shared-library",
            "~/repos/company-utils",
            "/absolute/path/to/package",
        ],
        "namespaces": {
            "mycompany": [
                "~/repos/mycompany-auth",
                "~/repos/mycompany-api",
                "~/repos/mycompany-core",
            ],
            "plugins": ["./plugins/*", "~/repos/community-plugins/*"],
        },
        "standalone": {
            "dirs": ["notebooks", "scripts", "examples"],
        },
    }

    config_path = Path(project_path) / f".{PROJECT_NAME}.json.example"
    with open(config_path, "w") as f:
        json.dump(example, f, indent=2)

    print(f"Created example config at {config_path.as_posix()}")
