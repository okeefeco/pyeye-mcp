"""Input validation and sanitization for file paths and user inputs."""

import contextlib
import os
import re
import threading
import time
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
        r"^/private/var/run/secrets/",  # ...as /var/run resolves on macOS (#909 review)
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
        """Reject a target any of whose *forms* is restricted (:func:`restricted_reason`).

        The system directory itself counts too: "/etc" (from "../../etc") must
        not slip past "^/etc/" for lack of a trailing slash. Case is ignored
        (#939). Results are checked by the same predicate, on the same forms
        (``resolver.restricted_path``, #1019).
        """
        stores = credential_stores()  # one look at the stores for every form
        for form in forms:
            reason = restricted_reason(form, stores)
            if reason is not None:
                raise ValidationError(f"Path resolves to restricted location: {reason}")

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

        The resolved form resolves the RAW join, never the lexical form: the OS
        follows a symlink before ``..``, so ``l_tmp/../etc`` with ``l_tmp`` ->
        ``/tmp`` is ``/etc`` on disk, though it collapses lexically to
        ``<root>/etc`` (as :meth:`_final_forms` does, #856 review; #939 review).
        """
        if path.is_absolute():
            lexical, raw = absolute_path(path), path
        elif anchor_root is not None:
            lexical, raw = absolute_path(anchor(path, anchor_root)), Path(anchor_root) / path
        else:
            lexical, raw = absolute_path(path), path
        resolved = normalize_path(raw)
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


class _CredentialStores:
    """Where the credential stores are: below any user home, or where one links (#909, #1019)."""

    def __init__(self, pattern: re.Pattern[str], linked: tuple[tuple[str, str], ...]) -> None:
        self.pattern = pattern
        #: ``(resolved location, store)`` for each store below the server's home
        #: that is itself a link elsewhere (``~/.ssh -> /data/keys``), lowercased.
        self.linked = linked

    def match(self, form: str) -> str | None:
        """The store *form* (POSIX, ending ``/``) is, or is inside; else ``None``."""
        found = self.pattern.match(form)
        if found:
            return found.group(1)
        lowered = form.lower()
        for location, store in self.linked:
            if lowered.startswith(location + "/"):
                return store
        return None


#: Every path below a home whose link state decides where a store is: each
#: store and each of its parents below the home (``.config`` for
#: ``.config/gcloud``). The cache key reads them, so a relink rebuilds (#1019).
_STORE_LINK_PATHS: tuple[str, ...] = tuple(
    dict.fromkeys(
        PurePosixPath(*PurePosixPath(store).parts[: depth + 1]).as_posix()
        for store in PathValidator.CREDENTIAL_PATHS
        for depth in range(len(PurePosixPath(store).parts))
    )
)

#: The directories holding those entries, relative to the home ("" is the home).
_STORE_LINK_DIRS: tuple[str, ...] = tuple(
    dict.fromkeys(
        "" if (parent := PurePosixPath(rel).parent.as_posix()) == "." else parent
        for rel in _STORE_LINK_PATHS
    )
)

#: A directory changed this recently may change again within the same
#: timestamp tick (ext4 uses a coarse clock; FAT has 2 s), so its times can't
#: be trusted to show the next change: the full link check runs instead.
_RECENT_NS = 2_000_000_000

#: Whether ``st_ctime`` is the inode CHANGE time, which ``touch`` and
#: ``os.utime`` can't set back: POSIX. On Windows it is the creation time.
_CTIME_IS_CHANGE = os.name != "nt"

#: ``(home spelling or None, the times of each _STORE_LINK_DIRS entry)``: cheap.
_DirKey = tuple[str | None, tuple[tuple[int, int] | None, ...]]
#: ``(dir key, link target of the home and of each _STORE_LINK_PATHS entry)``.
_StoreKey = tuple[_DirKey, tuple[str | None, ...]]


def _home_spelling() -> str | None:
    """The server's home as ``$HOME`` spells it (POSIX), or ``None`` if it can't be found."""
    try:
        return Path.home().as_posix()
    except (RuntimeError, KeyError, OSError):
        return None


def _dir_times(path: str) -> tuple[int, int] | None:
    """``(mtime, ctime)`` of directory *path* in ns (ctime 0 on Windows), or ``None``.

    The ctime is what makes the key hard to fool on POSIX: a link made, removed
    or repointed moves it, and so does setting the mtime back with ``touch -d``,
    which can't set it.
    """
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    return (st.st_mtime_ns, st.st_ctime_ns if _CTIME_IS_CHANGE else 0)


def _dir_key(home: str | None) -> _DirKey:
    """The home's spelling and the times of the directories its stores sit in (two ``stat``).

    Making, removing or repointing a link in a directory changes its mtime and
    (POSIX) its ctime, so this changes whenever a store's own link does, except
    within one tick of an earlier change (see :data:`_RECENT_NS`).
    """
    if home is None:
        return (None, ())
    root = home.rstrip("/")
    return (home, tuple(_dir_times(f"{root}/{d}" if d else root) for d in _STORE_LINK_DIRS))


def _link_target(path: str) -> str | None:
    """Where the symlink or junction *path* points, or ``None`` if it isn't one."""
    try:
        return os.readlink(path)
    except (OSError, ValueError):
        return None


def _store_key() -> _StoreKey:
    """What the stores' locations depend on: the home, its store directories, every link.

    The full key: :func:`_dir_key` plus one ``readlink`` of the home and of
    each :data:`_STORE_LINK_PATHS` entry.
    """
    home = _home_spelling()
    if home is None:
        return ((None, ()), ())
    root = home.rstrip("/")
    links = (_link_target(root),) + tuple(
        _link_target(f"{root}/{rel}") for rel in _STORE_LINK_PATHS
    )
    return (_dir_key(home), links)


def _build_credential_stores(home_spelling: str | None) -> _CredentialStores:
    """The stores for the server's home *home_spelling* (see :class:`_StoreCache`)."""
    homes = list(PathValidator.USER_HOMES)
    linked: dict[str, str] = {}
    # The home both as spelled ($HOME) and resolved: with a symlinked home
    # (NFS/autofs /home/u -> /data/u) the resolved form, which the walks and
    # the resolved check see, names neither the spelling nor a fixed root
    # (#909 review). No resolvable home: the fixed roots still apply.
    if home_spelling is not None:
        with contextlib.suppress(RuntimeError, OSError):
            home = Path(home_spelling)
            resolved_home = normalize_path(home)
            for spelling in dict.fromkeys([home.as_posix(), resolved_home.as_posix()]):
                homes.append("^" + re.escape(spelling.rstrip("/")) + "/")
            for store in PathValidator.CREDENTIAL_PATHS:
                with contextlib.suppress(RuntimeError, OSError):
                    location = normalize_path(home / store).as_posix().rstrip("/").lower()
                    if location != (resolved_home / store).as_posix().rstrip("/").lower():
                        linked.setdefault(location, store)
    stores = "|".join(re.escape(name) for name in PathValidator.CREDENTIAL_PATHS)
    pattern = re.compile(f"(?:{'|'.join(homes)})({stores})/", re.IGNORECASE)
    return _CredentialStores(pattern, tuple(linked.items()))


class _StoreCache:
    """Every user home followed by a credential store, plus each linked store (#909, #1019).

    :data:`PathValidator.USER_HOMES` plus the server's own home, as spelled and
    resolved. A store below that home which is itself a link
    (``~/.ssh -> /data/keys``) is also matched at its resolved location: a file
    in it resolves there, spelled below no home.

    A build is served only for the :func:`_store_key` it was built from: the
    home's spelling, and every link of a store or of one of its parents below
    the home. So a build made for one home is never served for another (a
    build racing a test's patched home can't leave a stale answer), and a store
    linked, removed or repointed after start-up (a profile switcher relinking
    ``~/.aws``) is seen at once. The build runs under a lock.

    The full key costs a ``readlink`` per store path, too much for the walkers'
    per-entry prune (#1028 review), so each call checks the cheap
    :func:`_dir_key` first: unchanged, and no store directory changed in the
    last :data:`_RECENT_NS`, means no link changed either. Otherwise the full
    key decides. ``cache_clear()`` forgets the last build.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._built: tuple[_StoreKey, _CredentialStores] | None = None

    def __call__(self) -> _CredentialStores:
        built = self._built
        if built is not None:
            dir_key = _dir_key(_home_spelling())
            if dir_key == built[0][0] and not _recently_changed(dir_key):
                return built[1]
        key = _store_key()
        if built is not None and built[0] == key:
            return built[1]
        with self._lock:
            built = self._built
            if built is None or built[0] != key:
                built = (key, _build_credential_stores(key[0][0]))
                self._built = built
        return built[1]

    def cache_clear(self) -> None:
        """Forget the last build, so the next call rebuilds."""
        with self._lock:
            self._built = None


def _recently_changed(dir_key: _DirKey) -> bool:
    """Whether a store directory changed within :data:`_RECENT_NS`, so its times can't vouch."""
    now = time.time_ns()
    return any(times is not None and now - max(times) < _RECENT_NS for times in dir_key[1])


_credential_pattern = _StoreCache()


def credential_stores() -> _CredentialStores:
    """Where the credential stores are now (:class:`_StoreCache`), to check several forms with.

    A caller checking many paths in one go (a walk, every form of one path)
    takes one snapshot and passes it to :func:`credential_path`,
    :func:`restricted_reason` or :func:`restricted_dir`, so the stores' links
    are looked at once rather than per path (#1028 review).
    """
    return _credential_pattern()


def credential_path(form: str | Path, stores: _CredentialStores | None = None) -> str | None:
    """The credential store *form* is, or is inside, below a user home; else ``None`` (#909).

    A store below the server's home that is a link counts at its target too
    (#1019). *stores* is a :func:`credential_stores` snapshot; ``None`` takes one.
    """
    if stores is None:
        stores = _credential_pattern()
    return stores.match(Path(form).as_posix().rstrip("/") + "/")


def restricted_reason(form: str | Path, stores: _CredentialStores | None = None) -> str | None:
    """Why the path *form* is restricted, or ``None``: the ONE predicate (#1019).

    *form* is one spelling of a path (lexical or resolved; callers check every
    form they have). It is restricted when it is, or is inside, a restricted
    directory (:data:`_RESTRICTED_DIRS`, the literals of the anchored
    :data:`PathValidator.RESTRICTED_TARGETS`; the reason is its pattern) or a
    credential store (:func:`credential_path`). Case is ignored (#939). Inputs
    (:meth:`PathValidator._check_targets`), results (``resolver.restricted_path``)
    and the walkers (:func:`restricted_dir`) all apply it, so they can't drift.
    *stores* is a :func:`credential_stores` snapshot; ``None`` takes one.
    """
    as_dir = Path(form).as_posix().rstrip("/") + "/"
    lowered = as_dir.lower()
    for directory in _RESTRICTED_DIRS:
        if lowered.startswith(directory.lower() + "/"):
            return f"^{directory}/"
    if (name := credential_path(as_dir, stores)) is not None:
        return f"the credential store {name} in a user home"
    return None


def restricted_dir(resolved: str | Path, stores: _CredentialStores | None = None) -> bool:
    """Whether the RESOLVED directory *resolved* is, or is inside, a restricted directory.

    The prune test every directory walk applies (#856 ruling): a route the
    input checks miss (a symlinked parent, a new scope form) still can't
    descend into a system directory or a credential store (#909), including a
    store that is itself a link (#1019). It is :func:`restricted_reason`, so
    walks, inputs and results agree. POSIX forms only, as the deny-list is.
    A walk passes one :func:`credential_stores` snapshot for all its entries.
    """
    return restricted_reason(resolved, stores) is not None


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

        # Validate based on parameter names. project_path first: the others are
        # anchored on it, so a refusal it causes must name it, not them (#949 review).
        arguments = sorted(bound.arguments.items(), key=lambda item: item[0] != "project_path")
        for param_name, value in arguments:
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
                            # POSIX, never str(): native backslashes on Windows
                            # would reach the config and the response (#717, #953).
                            validated_list.append(
                                validated.as_posix()
                                if isinstance(validated, PurePath)
                                else ensure_posix_path(str(validated))
                            )
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
