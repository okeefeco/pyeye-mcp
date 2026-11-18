"""Input validation and sanitization for file paths and user inputs."""

import contextlib
import functools
import re
from pathlib import Path, PurePath, PurePosixPath
from typing import Any

from .exceptions import ValidationError
from .path_utils import absolute_path, anchor, ensure_posix_path, normalize_path, relative_within


class PathValidator:
    """Validates and sanitizes file paths for security."""

    #: Substrings that reject a path outright, with how the error names them
    #: (docs fact ``security.path_checks``).
    REJECTED_SEQUENCES: tuple[tuple[str, str], ...] = (
        ("\x00", "null bytes"),
        ("...", "suspicious triple dots"),
    )

    # Patterns for potentially dangerous file names
    DANGEROUS_NAMES = [
        r"\.git/",  # Git directory
        r"\.ssh/",  # SSH keys
        r"\.aws/",  # AWS credentials
        r"^\.env$",  # Environment files
        r"\.pem$",  # Certificate files
        r"\.key$",  # Key files
        r"^/etc/",  # System config (Unix)
        r"^/proc/",  # Process info (Unix)
        r"^/sys/",  # System info (Unix)
    ]

    #: Checked against every form of the target (:meth:`check_forms`), ignoring
    #: case (a case-insensitive macOS volume reads "/ETC/passwd" as /etc). Every
    #: pattern is ANCHORED (#939): a check that matched a component anywhere
    #: refused ~/dev/proj, /srv/etc/lib and a project's own etc/ package. The
    #: anchored forms still catch every route to these directories, because
    #: since #856 each caller path is checked anchored and resolved.
    RESTRICTED_TARGETS: tuple[str, ...] = (
        r"^/etc/",
        r"^/private/etc/",  # macOS: /etc resolves here (#856 review)
        r"^/root/",
        r"^/proc/",
        r"^/sys/",
        r"^/dev/",
        r"^/boot/",  # #909
        r"^/run/secrets/",  # container secrets (#909)
        r"^/var/run/secrets/",  # Kubernetes service-account tokens (#909)
        r"^/var/root/",  # macOS root's home (#909)
        r"^/private/var/root/",  # ...as it resolves on macOS (#909)
    )

    #: Credential stores, refused (and pruned in walks) directly below any user
    #: home (:data:`USER_HOMES`), the entry itself or anything inside it (#909).
    #: Unlike :data:`RESTRICTED_TARGETS` they define no ancestors: a scan of
    #: ``~``, ``/home`` or ``/Users`` works and skips them. A project placed
    #: INSIDE one (``~/.config/gh/x``) is refused, as intended.
    CREDENTIAL_PATHS: tuple[str, ...] = (
        ".ssh",
        ".aws",
        ".gnupg",
        ".config/gcloud",
        ".azure",
        ".kube",
        ".docker",
        ".config/gh",
        ".netrc",
        ".pypirc",
        ".pgpass",
        ".git-credentials",
        ".npmrc",
    )

    #: Where a user home is, as anchored patterns: every one, including a home
    #: created after the server started, since nothing is enumerated. The
    #: server's own home (``Path.home()``, read once per process) is added at
    #: use, for a ``$HOME`` outside these roots (#909).
    USER_HOMES: tuple[str, ...] = (r"^/home/[^/]+/", r"^/Users/[^/]+/", r"^/root/")

    @classmethod
    def _check_spelling(cls, path_str: str) -> None:
        """Reject a path by how it's spelled, before anything resolves it.

        Null bytes and patterns that might be attacks are rejected even if the
        path doesn't exist. Where a path LEADS is :meth:`_check_targets`' job,
        on its anchored forms: a directory name inside the path proves nothing
        (#939).
        """
        for sequence, described in cls.REJECTED_SEQUENCES:
            if sequence in path_str:
                raise ValidationError(f"Path contains {described}")

    @classmethod
    def _check_targets(cls, forms: list[str]) -> None:
        """Reject a target any of whose *forms* matches :data:`RESTRICTED_TARGETS`.

        The system directory itself counts too: "/etc" (from "../../etc") must
        not slip past "^/etc/" for lack of a trailing slash. Case is ignored
        (#939).
        """
        for form in forms:
            as_dir = form.rstrip("/") + "/"
            for pattern in cls.RESTRICTED_TARGETS:
                if re.search(pattern, as_dir, re.IGNORECASE):
                    raise ValidationError(f"Path resolves to restricted location: {pattern}")
            if (name := credential_path(form)) is not None:
                raise ValidationError(
                    f"Path resolves to restricted location: the credential store {name} "
                    "in a user home"
                )

    @classmethod
    def validate_final(cls, path: str | Path, root: str | Path) -> Path:
        """Check *path* in the form the tool will use it; return the caller's spelling (#856).

        Unlike :meth:`validate_path`, a relative *path* is ALWAYS anchored on
        *root* (``path_utils.anchor``, as the tool anchors it), with or without
        ``..``, and both forms are checked: the lexical one (symlinks kept) and
        the resolved one (symlinks followed), so a symlink inside the project
        that points at a system directory is caught, while a project under a
        symlinked root (macOS ``/tmp`` -> ``/private/tmp``) still passes.

        Raises:
            ValidationError: If the path is empty, spelled suspiciously, or any
                form of it lands in a restricted location.
        """
        path_str, forms = cls._final_forms(path, root)
        cls._check_targets(forms)
        return Path(path_str)

    @classmethod
    def validate_scan_root(cls, path: str | Path, root: str | Path) -> Path:
        """:meth:`validate_final` for a directory that will be WALKED (#856 ruling).

        A scan root (a scope's directory, a package, a namespace or standalone
        dir) is also refused when it is an ANCESTOR of a restricted directory
        ("/", and "/private" on macOS): walking it would descend into one. The
        walkers prune restricted directories too (:func:`restricted_dir`); this
        refuses the scan up front, with a clear error.

        Raises:
            ValidationError: As :meth:`validate_final`, or if any form of *path*
                is an ancestor of a restricted directory.
        """
        path_str, forms = cls._final_forms(path, root)
        cls._check_targets(forms)
        for form in forms:
            if (form.rstrip("/") or "/") in _RESTRICTED_ANCESTORS:
                raise ValidationError(
                    f"Path is an ancestor of a restricted location: {form} "
                    "(a scan from it would reach a system directory)"
                )
        return Path(path_str)

    @classmethod
    def _final_forms(cls, path: str | Path, root: str | Path) -> tuple[str, list[str]]:
        """``(spelling, forms)``: *path* spell-checked, and its lexical and resolved forms."""
        if not path:
            raise ValidationError("Path cannot be empty")
        path_str = Path(path).as_posix()
        cls._check_spelling(path_str)
        try:
            given = Path(path_str)
            lexical = absolute_path(anchor(given, root))
            # Resolve the RAW join, not the lexical form: "l_tmp/../etc" with
            # l_tmp -> /tmp is /etc on disk, though it collapses lexically to
            # "<root>/etc" (#856 review). The OS follows the symlink first.
            resolved = normalize_path(given if given.is_absolute() else Path(root) / given)
        except (ValueError, RuntimeError, OSError) as e:
            raise ValidationError(f"Invalid path: {e}") from e
        return path_str, list(dict.fromkeys([lexical.as_posix(), resolved.as_posix()]))

    @staticmethod
    def check_forms(path: Path, anchor_root: str | Path | None = None) -> tuple[Path, list[str]]:
        """``(resolved, forms)``: the deny-list checks the target's lexical and resolved forms.

        The target is checked both **lexically** (anchored, ``..`` collapsed,
        symlinks kept) and **resolved** (symlinks followed). Either matching
        rejects it: on macOS ``/etc`` resolves to ``/private/etc``, which the
        resolved form alone never matches, and a symlink inside the project that
        points at ``/etc`` is caught only by the resolved form.

        - An absolute path: as given.
        - A relative path with *anchor_root* (where the tool will anchor it):
          ALWAYS anchored there, ``..`` or not (#856).
        - A relative path without one: anchored on the cwd, where the OS would
          resolve it (#939). The deny-list is all anchored patterns, so a path
          checked only as written ("etc/passwd") would never match.
        """
        if path.is_absolute():
            lexical = absolute_path(path)
        elif anchor_root is not None:
            lexical = absolute_path(anchor(path, anchor_root))
        else:
            lexical = absolute_path(path)
        resolved = normalize_path(lexical)
        return resolved, list(dict.fromkeys([lexical.as_posix(), resolved.as_posix()]))

    @classmethod
    def validate_path(
        cls,
        path: str | Path,
        base_path: str | Path | None = None,
        anchor_root: str | Path | None = None,
    ) -> Path:
        """Validate and sanitize a file path.

        The checks run on where the path really goes, but a relative path is
        returned as the caller wrote it, for the tool to anchor on its project
        (``path_utils.anchor``, #842, #843).

        Args:
            path: The path to validate
            base_path: Optional base path to restrict access within
            anchor_root: The directory a relative *path* is relative to (the
                call's ``project_path``). A relative path containing ``..`` is
                checked as anchored there; without it, as anchored on the cwd.

        Returns:
            Validated Path object

        Raises:
            ValidationError: If the path is invalid or potentially dangerous
        """
        if not path:
            raise ValidationError("Path cannot be empty")

        # Convert to string for validation
        path_str = Path(path).as_posix()

        cls._check_spelling(path_str)

        # Convert to Path object
        try:
            path_obj = Path(path_str)
            # The deny-list below must see the real target, so an absolute path,
            # or a relative one with ``..``, is resolved for the checks: a
            # relative one where the tool will anchor it (*anchor_root*), else
            # on the cwd as before. Only the checks use it; a relative path is
            # returned unchanged (#842, #843).
            resolved_path, forms = cls.check_forms(path_obj, anchor_root)
        except (ValueError, RuntimeError) as e:
            raise ValidationError(f"Invalid path: {e}") from e

        cls._check_targets(forms)

        # If base_path is provided, ensure the path is within it
        if base_path:
            base = normalize_path(base_path)
            # Resolve for this check only
            check_path = (
                resolved_path if resolved_path.is_absolute() else normalize_path(resolved_path)
            )
            if relative_within(check_path, base) is None:
                raise ValidationError(
                    f"Path {check_path.as_posix()} is outside base directory {base.as_posix()}"
                )

        # Check for dangerous file names
        path_str_normalized = resolved_path.as_posix().replace("\\", "/")
        for pattern in cls.DANGEROUS_NAMES:
            if re.search(pattern, path_str_normalized, re.IGNORECASE):
                # Log warning but don't block - these might be legitimate
                import logging

                logging.getLogger(__name__).warning(
                    f"Accessing potentially sensitive path: {path_str_normalized}"
                )

        # The checks above ran on the resolved form. Hand back the caller's
        # spelling, made absolute: a symlinked project_path must stay as the
        # agent gave it, or every location comes back under the real path and
        # can't be matched to the agent's own paths (#603, #717).
        if path_obj.is_absolute():
            return absolute_path(path_str)
        return path_obj


#: The restricted DIRECTORIES: the literal of each anchored deny-list pattern
#: ("^/private/etc/" -> "/private/etc"). Every pattern is anchored since #939;
#: the filter keeps an unanchored one, if ever added, from defining ancestors:
#: it would name no fixed directory.
_RESTRICTED_DIRS: tuple[str, ...] = tuple(
    pattern[1:].rstrip("/")
    for pattern in PathValidator.RESTRICTED_TARGETS
    if pattern.startswith("^")
)

#: Every proper ancestor of a restricted directory: "/" and, for macOS's
#: /private/etc, "/private". A scan rooted at one would walk into a restricted
#: directory, so :meth:`PathValidator.validate_scan_root` refuses it.
_RESTRICTED_ANCESTORS: frozenset[str] = frozenset(
    parent.as_posix() for d in _RESTRICTED_DIRS for parent in PurePosixPath(d).parents
)


@functools.cache
def _credential_pattern() -> re.Pattern[str]:
    """Every user home followed by a credential store, as one pattern (#909).

    Built once per process: :data:`PathValidator.USER_HOMES` plus the server's
    own home, whose ``$HOME`` can't move for a running process.
    """
    homes = list(PathValidator.USER_HOMES)
    # No resolvable home: the fixed roots still apply.
    with contextlib.suppress(RuntimeError, KeyError):
        homes.append("^" + re.escape(Path.home().as_posix().rstrip("/")) + "/")
    stores = "|".join(re.escape(name) for name in PathValidator.CREDENTIAL_PATHS)
    return re.compile(f"(?:{'|'.join(homes)})({stores})/", re.IGNORECASE)


def credential_path(form: str | Path) -> str | None:
    """The credential store *form* is, or is inside, below a user home; else ``None`` (#909)."""
    match = _credential_pattern().match(Path(form).as_posix().rstrip("/") + "/")
    return match.group(1) if match else None


def restricted_dir(resolved: str | Path) -> bool:
    """Whether the RESOLVED directory *resolved* is, or is inside, a restricted directory.

    The prune test every directory walk applies (#856 ruling): a route the
    input checks miss (a symlinked parent, a new scope form) still can't
    descend into a system directory or a credential store (#909). Case is
    ignored, as in :meth:`PathValidator._check_targets` (#939). POSIX forms
    only, as the deny-list is.
    """
    form = Path(resolved).as_posix().rstrip("/").lower() + "/"
    if any(form.startswith(d.lower() + "/") for d in _RESTRICTED_DIRS):
        return True
    return credential_path(form) is not None


def unwalkable_root(resolved: str | Path) -> bool:
    """Whether a walk rooted at the RESOLVED *resolved* can't be made safe by pruning.

    True for a restricted directory and for an ancestor of one: the walkers
    that take no prune hook (the recursive file watcher) must not start there.
    """
    form = Path(resolved).as_posix().rstrip("/") or "/"
    return restricted_dir(form) or form in _RESTRICTED_ANCESTORS


class InputValidator:
    """General input validation utilities."""

    @staticmethod
    def validate_identifier(name: str, allow_dots: bool = True) -> str:
        """Validate a Python identifier or module name.

        Args:
            name: The identifier to validate
            allow_dots: Whether to allow dots (for module names)

        Returns:
            The validated identifier

        Raises:
            ValidationError: If the identifier is invalid
        """
        if not name:
            raise ValidationError("Identifier cannot be empty")

        # Check length
        if len(name) > 255:
            raise ValidationError("Identifier too long")

        # Check for null bytes
        if "\x00" in name:
            raise ValidationError("Identifier contains null bytes")

        # Validate format
        if allow_dots:
            # Module name format: word.word.word
            pattern = r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$"
        else:
            # Simple identifier
            pattern = r"^[a-zA-Z_][a-zA-Z0-9_]*$"

        if not re.match(pattern, name):
            raise ValidationError(f"Invalid identifier format: {name}")

        return name

    @staticmethod
    def validate_line_number(line: Any, max_line: int = 1000000) -> int:
        """Validate a line number.

        Args:
            line: The line number to validate
            max_line: Maximum allowed line number

        Returns:
            The validated line number

        Raises:
            ValidationError: If the line number is invalid
        """
        try:
            line_num = int(line)
        except (TypeError, ValueError) as e:
            raise ValidationError(f"Invalid line number: {line}") from e

        if line_num < 1:
            raise ValidationError("Line number must be positive")

        if line_num > max_line:
            raise ValidationError(f"Line number too large: {line_num}")

        return line_num

    @staticmethod
    def validate_column_number(column: Any, max_column: int = 10000) -> int:
        """Validate a column number.

        Args:
            column: The column number to validate
            max_column: Maximum allowed column number

        Returns:
            The validated column number

        Raises:
            ValidationError: If the column number is invalid
        """
        try:
            col_num = int(column)
        except (TypeError, ValueError) as e:
            raise ValidationError(f"Invalid column number: {column}") from e

        if col_num < 0:
            raise ValidationError("Column number must be non-negative")

        if col_num > max_column:
            raise ValidationError(f"Column number too large: {col_num}")

        return col_num


def validate_mcp_inputs(func: Any) -> Any:
    """Decorator to validate inputs for MCP tool functions.

    This decorator validates common MCP tool parameters and raises
    ValidationError for invalid inputs rather than returning error dicts.
    Properly handles both sync and async functions.
    """
    import functools
    import inspect

    def validate_arguments(sig: Any, args: Any, kwargs: Any) -> Any:
        """Common validation logic for both sync and async wrappers."""
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()

        # Get function name to apply specific validation rules
        func_name = func.__name__

        # Relative paths in this call are relative to its project (#842, #843).
        raw_project = bound.arguments.get("project_path")
        project_root = raw_project if isinstance(raw_project, str | Path) else "."

        # Validate based on parameter names
        for param_name, value in bound.arguments.items():
            if value is None:
                continue

            # File path validation
            if param_name in ["file", "file_path", "path", "project_path"]:
                try:
                    # A file is relative to the call's project; project_path
                    # itself is relative to the cwd (#842, #843).
                    root = "." if param_name == "project_path" else project_root
                    validated = PathValidator.validate_path(value, anchor_root=root)
                    # POSIX, never str(): str() gives native backslashes on
                    # Windows, and the value is echoed back to the agent (#717).
                    bound.arguments[param_name] = (
                        validated.as_posix()
                        if isinstance(validated, PurePath)
                        else ensure_posix_path(str(validated))
                    )
                except ValidationError as e:
                    # Raise the error to be handled by the exception handler
                    raise ValidationError(
                        f"Invalid {param_name}: {e}", parameter=param_name, value=str(value)
                    ) from e

            # Line number validation
            elif param_name == "line":
                try:
                    bound.arguments[param_name] = InputValidator.validate_line_number(value)
                except ValidationError as e:
                    raise ValidationError(
                        f"Invalid line number: {e}", parameter="line", value=str(value)
                    ) from e

            # Column number validation
            elif param_name == "column":
                try:
                    bound.arguments[param_name] = InputValidator.validate_column_number(value)
                except ValidationError as e:
                    raise ValidationError(
                        f"Invalid column number: {e}", parameter="column", value=str(value)
                    ) from e

            # Module/identifier name validation
            elif param_name in [
                "name",
                "module_name",
                "function_name",
                "import_path",
                "symbol_name",
            ]:
                try:
                    # Special handling for find_symbol: allow compound symbols (dots)
                    if param_name == "name" and func_name == "find_symbol":
                        # For find_symbol, allow dots in the name parameter for compound symbols
                        bound.arguments[param_name] = InputValidator.validate_identifier(
                            value, allow_dots=True
                        )
                    else:
                        # Standard validation for other cases
                        bound.arguments[param_name] = InputValidator.validate_identifier(
                            value,
                            allow_dots=param_name in ["module_name", "import_path", "symbol_name"],
                        )
                except ValidationError as e:
                    raise ValidationError(
                        f"Invalid {param_name}: {e}", parameter=param_name, value=str(value)
                    ) from e

            # List validation for paths
            elif param_name == "namespaces" and isinstance(value, dict):
                # configure_packages: each namespace's repo paths, checked where
                # they will be anchored, and passed on as the caller wrote them (#856).
                for namespace, ns_paths in value.items():
                    for i, item in enumerate(ns_paths or []):
                        try:
                            PathValidator.validate_scan_root(item, project_root)
                        except ValidationError as e:
                            raise ValidationError(
                                f"Invalid path at index {i} in namespaces[{namespace!r}]: {e}",
                                parameter=param_name,
                                value=str(item),
                                index=i,
                            ) from e

            elif param_name in [
                "paths",
                "repo_paths",
                "project_paths",
                "packages",
                "standalone_dirs",
            ]:
                if isinstance(value, list):
                    validated_list = []
                    for i, item in enumerate(value):
                        try:
                            validated = PathValidator.validate_path(item, anchor_root=project_root)
                            if param_name in ("packages", "standalone_dirs"):
                                # Directories to scan (#856 ruling): not "/" either.
                                PathValidator.validate_scan_root(item, project_root)
                            validated_list.append(str(validated))
                        except ValidationError as e:
                            raise ValidationError(
                                f"Invalid path at index {i} in {param_name}: {e}",
                                parameter=param_name,
                                value=str(item),
                                index=i,
                            ) from e
                    bound.arguments[param_name] = validated_list

        return bound

    # Get function signature once
    sig = inspect.signature(func)

    # Check if the function is async
    if inspect.iscoroutinefunction(func):  # not asyncio.*: deprecated in 3.14 (#763)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = validate_arguments(sig, args, kwargs)
            return await func(*bound.args, **bound.kwargs)

        return async_wrapper
    else:

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = validate_arguments(sig, args, kwargs)
            return func(*bound.args, **bound.kwargs)

        return sync_wrapper
