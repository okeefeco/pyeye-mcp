"""Configuration management for PyEye."""

import json
import logging
import os
from pathlib import Path
from typing import Any

from .async_utils import pruned_rglob
from .constants import CONFIG_FILE, CONFIG_FILES, GLOBAL_CONFIG_FILES, OVERRIDE_FILE, PROJECT_NAME
from .path_utils import normalize_path, path_to_key
from .project_layout import detect_src_layout
from .validation import PathValidator, ValidationError

logger = logging.getLogger(__name__)

#: The ``reason`` of a config entry the path check refused (#898), as distinct
#: from a ``package:`` path that merely doesn't exist (#842).
REJECTED_PATH = "rejected_path"

#: The top-level keys of the pyeye config that pyeye reads (docs facts
#: ``config.key.*``). ``tests/test_docs_facts_repo_config.py`` fails if code reads
#: a top-level key that isn't listed here.
CONFIG_KEYS: tuple[str, ...] = (
    "packages",
    "namespaces",
    "standalone",
    "scope_defaults",
    "scope_aliases",
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

    def __init__(self, project_path: str = ".") -> None:
        """Initialize configuration for a project.

        Args:
            project_path: Root path of the project
        """
        self.project_path = normalize_path(project_path)
        self.config: dict[str, Any] = {}
        self.has_explicit_config: bool = False
        self.load_config()

    def load_config(self) -> None:
        """Load configuration from various sources.

        Loading order (later sources override earlier ones):
        1. Global config (~/.config/pyeye/config.json)
        2. Project config files (.pyeye.json, pyproject.toml, etc.)
        3. Override file (.pyeye.override.json) - for local development
        4. Auto-discovery (if no packages configured)
        """
        # 1. Load global config first (lowest precedence)
        self._load_global_config()

        # 2. Load project config files
        for config_file in self.CONFIG_FILES:
            config_path = self.project_path / config_file
            if config_path.exists():
                self._load_from_file(config_path)
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

        ignored = self.get_ignored_top_level_keys()
        if ignored:
            logger.warning(self.ignored_top_level_keys_message(ignored))

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

    def _load_from_file(self, config_path: Path) -> None:
        """Load configuration from a file."""
        logger.info(f"Loading config from {config_path.as_posix()}")

        try:
            if config_path.suffix == ".json":
                with open(config_path) as f:
                    data = json.load(f)
                    if PROJECT_NAME in data:
                        self.config.update(data[PROJECT_NAME])
                    else:
                        self.config.update(data)

            elif config_path.suffix in [".yaml", ".yml"]:
                with open(config_path) as f:
                    import yaml

                    data = yaml.safe_load(f)
                    if PROJECT_NAME in data:
                        self.config.update(data[PROJECT_NAME])
                    else:
                        self.config.update(data)

            elif config_path.name == "pyproject.toml":
                import tomllib

                with open(config_path, "rb") as f:
                    data = tomllib.load(f)

                    # Read PyEye-specific config first
                    if "tool" in data and PROJECT_NAME in data["tool"]:
                        self.config.update(data["tool"][PROJECT_NAME])

                    # Read [tool.pyright] extraPaths — projects already declare
                    # their dependencies here, no need for duplicate .pyeye.json
                    self._read_pyright_extra_paths(data)

                    # Auto-detect source layouts from build backend metadata
                    # Only apply if no packages already configured
                    if not self.config.get("packages"):
                        self._detect_source_layout(data)

        except Exception as e:
            logger.error(f"Error loading config from {config_path.as_posix()}: {e}")

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
                for sibling in parent.iterdir():
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

    def _discover_venv_packages(self) -> list[str]:
        """Discover packages in virtualenv site-packages.

        Returns:
            List of site-packages paths
        """
        potential_packages = []
        venv_paths = [
            self.project_path / "venv" / "lib",
            self.project_path / ".venv" / "lib",
            self.project_path / "env" / "lib",
        ]

        for venv_path in venv_paths:
            if venv_path.exists():
                for site_packages in pruned_rglob("site-packages", venv_path):
                    potential_packages.append(str(site_packages))

        return potential_packages

    def _auto_discover(self) -> None:
        """Auto-discover package locations."""
        # Check for src layout first (most specific pattern)
        if self._discover_src_layout():
            return  # Don't look for other patterns if src/ found

        # Discover sibling packages and virtualenv packages
        potential_packages = []
        potential_packages.extend(self._discover_sibling_packages())
        potential_packages.extend(self._discover_venv_packages())

        if potential_packages:
            logger.info(f"Auto-discovered packages: {potential_packages}")
            self.config.setdefault("packages", []).extend(potential_packages)

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

    def _checked_package_dirs(self, normalised: str) -> list[str]:
        """The directories a normalised package entry names, each checked as a scan root.

        A glob names its matches, a plain entry itself if it exists. The one
        check of a package-path entry, for the getters and
        :meth:`rejected_paths` alike (#898).

        Raises:
            ValidationError: For the first directory the path check refuses.
        """
        if "*" in normalised:
            from glob import glob

            targets, keep_missing = glob(normalised), True
        else:
            targets, keep_missing = [normalised], False
        paths = []
        for target in targets:
            validated = PathValidator.validate_path(target)
            # A directory to scan: not "/" (or another ancestor of /etc) either.
            PathValidator.validate_scan_root(target, self.project_path)
            if keep_missing or validated.exists():
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
        return {
            ns: [
                normalised
                for p in paths
                if self._passes_path_check(normalised := self._normalise_config_path(p), ns)
            ]
            for ns, paths in namespaces.items()
        }

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

    def rejected_paths(self) -> list[dict[str, str]]:
        """Every config path entry the path check refuses, for the caller to see (#898).

        The getters skip a refused entry with a warning (#856); this reports the
        same entries, through the same checks, so a result can't silently omit a
        package the user configured (#568). One record per refused entry:
        ``{scope, path, reason: "rejected_path", detail}``, where ``scope`` is the
        scope it belongs to (``packages``, ``namespace:<name>`` or
        ``standalone``) and ``path`` is the entry as written. ``[]`` when none.
        """
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
                # get_namespaces checks the entry; get_package_paths, its directories.
                normalised = self._normalise_config_path(raw)
                record(
                    f"namespace:{ns}",
                    raw,
                    self._path_refusal(normalised) or self._package_refusal(raw),
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
            with open(config_path, "w") as f:
                json.dump(self.config, f, indent=2)
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
