#!/usr/bin/env python3
"""WorktreeCreate hook for Claude Code.

Replaces the default git worktree creation with a custom implementation
that supports re-entrant worktrees, a nested type-prefixed naming model,
and a configurable worktree location.

Input (JSON via stdin):
    session_id: str - Current session identifier
    cwd: str - Current working directory
    hook_event_name: str - Always "WorktreeCreate"
    name: str - Worktree name/identifier

Output:
    Prints absolute path to worktree directory on stdout.
    All logging goes to stderr and log file.
    Non-zero exit = creation failed.

Configuration:
    Branch types and settings are loaded from YAML config files:
    1. <this script's dir>/worktree_create.yaml  (bundled defaults)
    2. {repo}/.claude/hooks/worktree_create.yaml  (project overrides)
    Project config merges on top of the bundled defaults.

Worktree convention:
    The leading type prefix becomes its own directory level; branch and
    directory share the nested form (feat-123-desc -> feat/123-desc).
    Location is configurable (native .claude/worktrees by default;
    in-repo or sibling layouts opt-in via worktree_location).

Re-entrant:
    If a worktree already exists for the given name, returns its path
    without creating a new one.
"""

import json
import logging
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

LOG_FILE = Path.home() / ".claude" / "logs" / "worktree-create.log"
# Bundled default config lives next to this script so the hook is relocatable
# (e.g. when shipped inside a plugin under ${CLAUDE_PLUGIN_ROOT}).
DEFAULT_CONFIG = Path(__file__).resolve().parent / "worktree_create.yaml"
PROJECT_CONFIG_REL = Path(".claude") / "hooks" / "worktree_create.yaml"

logger = logging.getLogger("worktree-create")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    """Load a YAML file, returning empty dict if missing or unparseable."""
    if not path.is_file():
        logger.debug("Config not found: %s", path)
        return {}

    if yaml is not None:
        with open(path) as f:
            data = yaml.safe_load(f)
            logger.info("Loaded config: %s", path)
            return data if isinstance(data, dict) else {}

    # Fallback: minimal YAML subset parser for simple worktree config
    # Handles only what we need: top-level keys, lists of mappings
    return _parse_simple_yaml(path)


def _parse_simple_yaml(path: Path) -> dict:
    """Minimal YAML parser for worktree config when PyYAML is not available.

    Handles the specific structure we need:
    - Top-level scalar keys (work_dir_suffix: "-work")
    - Top-level list keys with mapping items (branch_types list)
    """
    logger.debug("Using simple YAML parser for: %s", path)
    result: dict = {}
    current_list_key: str | None = None
    current_item: dict | None = None
    branch_types: list[dict] = []

    with open(path) as f:
        for raw_line in f:
            line = raw_line.rstrip()

            # Skip empty lines and comments
            stripped = line.lstrip()
            if not stripped or stripped.startswith("#"):
                continue

            indent = len(line) - len(stripped)

            # Top-level key (no indent)
            if indent == 0 and ":" in stripped:
                # Flush any pending item
                if current_item is not None:
                    branch_types.append(current_item)
                    current_item = None

                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip()

                if not value:
                    current_list_key = key
                else:
                    # Remove surrounding quotes
                    value = value.strip("\"'")
                    result[key] = value
                    current_list_key = None
                continue

            # List item start (- canonical: ...)
            if stripped.startswith("- ") and current_list_key:
                if current_item is not None:
                    branch_types.append(current_item)

                item_content = stripped[2:].strip()
                current_item = {}
                if ":" in item_content:
                    k, _, v = item_content.partition(":")
                    v = v.strip()
                    current_item[k.strip()] = v
                continue

            # Continuation of list item (aliases: [...])
            if current_item is not None and ":" in stripped:
                k, _, v = stripped.partition(":")
                k = k.strip()
                v = v.strip()

                # Parse inline list [a, b, c]
                if v.startswith("[") and v.endswith("]"):
                    items = [i.strip().strip("\"'") for i in v[1:-1].split(",") if i.strip()]
                    current_item[k] = items
                else:
                    current_item[k] = v.strip("\"'")
                continue

    # Flush last item
    if current_item is not None:
        branch_types.append(current_item)

    if branch_types and current_list_key:
        result[current_list_key] = branch_types

    return result


def load_config(repo_root: Path) -> dict:
    """Load and merge bundled defaults + project config."""
    user_cfg = _load_yaml(DEFAULT_CONFIG)
    project_cfg = _load_yaml(repo_root / PROJECT_CONFIG_REL)

    # Start with user defaults
    config = {
        "worktree_location": user_cfg.get("worktree_location", "native"),
        "in_repo_dir": user_cfg.get("in_repo_dir", ".worktrees"),
        "work_dir_suffix": user_cfg.get("work_dir_suffix", "-work"),
        "branch_types": list(user_cfg.get("branch_types", [])),
    }

    # Merge project overrides (scalar settings: project wins)
    for key in ("worktree_location", "in_repo_dir", "work_dir_suffix"):
        if key in project_cfg:
            config[key] = project_cfg[key]

    if "branch_types" in project_cfg:
        # Build set of existing canonicals for dedup
        existing = {bt["canonical"] for bt in config["branch_types"]}
        for bt in project_cfg["branch_types"]:
            canonical = bt.get("canonical", "")
            if canonical in existing:
                # Replace existing entry (project overrides user)
                config["branch_types"] = [
                    bt if entry.get("canonical") == canonical else entry
                    for entry in config["branch_types"]
                ]
            else:
                config["branch_types"].append(bt)

    logger.debug(
        "Merged config: %d branch types, suffix=%r",
        len(config["branch_types"]),
        config["work_dir_suffix"],
    )
    return config


def build_prefix_map(config: dict) -> dict[str, str]:
    """Build prefix -> canonical mapping from config.

    Returns a dict where keys are all recognised prefixes (canonical + aliases)
    and values are the canonical name.
    """
    mapping: dict[str, str] = {}
    for bt in config.get("branch_types", []):
        canonical = bt.get("canonical", "")
        if not canonical:
            continue
        mapping[canonical] = canonical
        for alias in bt.get("aliases", []):
            mapping[alias] = canonical
    logger.debug("Prefix map: %s", mapping)
    return mapping


# ---------------------------------------------------------------------------
# Name parsing
# ---------------------------------------------------------------------------


def parse_name(name: str, prefix_map: dict[str, str]) -> tuple[str, str]:
    """Parse a worktree name into (branch_name, dir_name).

    The first segment (up to the first "/" or "-") is the type prefix. If it
    matches a known prefix or alias it is normalised to its canonical form and
    the name becomes a nested path. Branch and directory share that nested
    form, so the type prefix is always its own directory level:

        feat-361-desc     -> ("feat/361-desc", "feat/361-desc")
        feature/361-desc  -> ("feat/361-desc", "feat/361-desc")   # alias collapsed
        feat/361-desc     -> ("feat/361-desc", "feat/361-desc")   # already canonical
        bugfix-7-x        -> ("fix/7-x",       "fix/7-x")

    Unrecognised prefixes (and names with no separator) pass through unchanged:
        random-thing      -> ("random-thing", "random-thing")
        scratch           -> ("scratch",      "scratch")

    Returns:
        (branch_name, dir_name) — identical nested strings, so the worktree
        lives at <base>/<canonical>/<remainder>/ on branch <canonical>/<remainder>.
    """
    # The prefix runs up to the first separator, be it "/" (already path-like)
    # or "-" (flat form we normalise into a path).
    sep_index = next((i for i, ch in enumerate(name) if ch in "/-"), None)

    if sep_index is None:
        logger.debug("No separator in %r, using as-is", name)
        return name, name

    prefix = name[:sep_index]
    remainder = name[sep_index + 1 :]
    canonical = prefix_map.get(prefix)

    if canonical is None:
        logger.debug("Prefix %r not recognised, using name as-is", prefix)
        return name, name

    nested = f"{canonical}/{remainder}"
    logger.info(
        "Resolved prefix: %r -> canonical=%r nested=%s",
        prefix,
        canonical,
        nested,
    )
    return nested, nested


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def git(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run a git command, logging the invocation and result."""
    cmd = ["git", *args]
    logger.debug("Running: %s (cwd=%s)", " ".join(cmd), cwd or ".")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, check=False)
    if result.returncode != 0:
        logger.debug("git stderr: %s", result.stderr.strip())
    return result


def find_main_repo_root(cwd: str) -> Path | None:
    """Find the main git repo root, even if cwd is inside a worktree.

    Uses git's common-dir to resolve back to the main repo when
    invoked from within a worktree.
    """
    result = git("rev-parse", "--show-toplevel", cwd=cwd)
    if result.returncode != 0:
        return None
    toplevel = Path(result.stdout.strip())

    # Check if this is a worktree by comparing git-dir to common-dir
    git_dir = git("rev-parse", "--git-dir", cwd=cwd)
    common_dir = git("rev-parse", "--git-common-dir", cwd=cwd)

    if git_dir.returncode == 0 and common_dir.returncode == 0:
        git_dir_path = Path(git_dir.stdout.strip()).resolve()
        common_dir_path = Path(common_dir.stdout.strip()).resolve()

        if git_dir_path != common_dir_path:
            main_root = common_dir_path.parent
            logger.info(
                "CWD is inside a worktree (%s), resolved main repo: %s",
                toplevel,
                main_root,
            )
            return main_root

    return toplevel


def get_default_branch(repo_root: Path) -> str:
    """Determine the default branch for the repository.

    Checks in order:
    1. Remote HEAD symbolic ref (set on clone, no network call)
    2. Local 'main' branch
    3. Local 'master' branch
    4. HEAD as last resort
    """
    repo = str(repo_root)

    result = git("symbolic-ref", "refs/remotes/origin/HEAD", cwd=repo)
    if result.returncode == 0:
        ref = result.stdout.strip()
        branch = ref.rsplit("/", 1)[-1]
        logger.info("Default branch from origin/HEAD: %s", branch)
        return branch

    for candidate in ("main", "master"):
        result = git("rev-parse", "--verify", f"refs/heads/{candidate}", cwd=repo)
        if result.returncode == 0:
            logger.info("Default branch by local check: %s", candidate)
            return candidate

    logger.warning("No default branch found, falling back to HEAD")
    return "HEAD"


def find_worktree_for_branch(repo_root: Path, branch_name: str) -> Path | None:
    """Find an existing worktree that has the given branch checked out."""
    result = git("worktree", "list", "--porcelain", cwd=str(repo_root))
    if result.returncode != 0:
        return None

    current_path: Path | None = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = Path(line[9:])
        elif line.startswith("branch refs/heads/") and current_path is not None:
            if line[18:] == branch_name:
                return current_path

    return None


def branch_exists_local(repo_root: Path, branch_name: str) -> bool:
    """Check if a branch exists locally."""
    result = git("rev-parse", "--verify", f"refs/heads/{branch_name}", cwd=str(repo_root))
    return result.returncode == 0


def branch_exists_remote(repo_root: Path, branch_name: str) -> bool:
    """Check if a branch exists on the remote (origin)."""
    result = git(
        "rev-parse",
        "--verify",
        f"refs/remotes/origin/{branch_name}",
        cwd=str(repo_root),
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Worktree location
# ---------------------------------------------------------------------------


def resolve_work_base(repo_root: Path, config: dict) -> tuple[Path, str | None]:
    """Resolve the parent directory worktrees are created under.

    Returns (work_base, exclude_rel):
        work_base   - directory that holds the per-branch worktree dirs
        exclude_rel - repo-relative path to add to .git/info/exclude for
                      in-repo layouts, or None for the sibling layout
                      (which lives outside the repo and needs no exclude).

    Layouts (config key ``worktree_location``):
        native  -> <repo>/.claude/worktrees/   (default, matches Claude Code)
        in-repo -> <repo>/<in_repo_dir>/        (e.g. .worktrees)
        sibling -> <repo>-parent/<repo><work_dir_suffix>/   (legacy)
    """
    location = config.get("worktree_location", "native")

    if location == "sibling":
        suffix = config.get("work_dir_suffix", "-work")
        return repo_root.parent / f"{repo_root.name}{suffix}", None

    if location == "in-repo":
        sub = config.get("in_repo_dir", ".worktrees").strip("/")
        return repo_root / sub, f"{sub}/"

    if location != "native":
        logger.warning("Unknown worktree_location %r, defaulting to native", location)
    return repo_root / ".claude" / "worktrees", ".claude/worktrees/"


def ensure_excluded(repo_root: Path, rel_dir: str) -> None:
    """Add ``rel_dir`` to the repo's .git/info/exclude.

    In-repo worktrees would otherwise appear as untracked content in the
    main repo's ``git status``. Using info/exclude keeps this local — it
    never touches a tracked .gitignore and needs no commit.
    """
    result = git("rev-parse", "--git-common-dir", cwd=str(repo_root))
    if result.returncode != 0:
        logger.warning("Could not resolve git-common-dir; skipping exclude")
        return

    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = (repo_root / common).resolve()

    exclude_file = common / "info" / "exclude"
    entry = rel_dir if rel_dir.endswith("/") else f"{rel_dir}/"

    existing = exclude_file.read_text() if exclude_file.is_file() else ""
    for line in existing.splitlines():
        if line.strip() in (entry, entry.rstrip("/")):
            logger.debug("Exclude entry already present: %s", entry)
            return

    exclude_file.parent.mkdir(parents=True, exist_ok=True)
    prefix = "\n" if existing and not existing.endswith("\n") else ""
    with open(exclude_file, "a") as f:
        f.write(f"{prefix}{entry}\n")
    logger.info("Added %s to %s", entry, exclude_file)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging() -> None:
    """Configure logging to file and stderr (never stdout)."""
    logger.setLevel(logging.DEBUG)

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.INFO)
    stderr_handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))

    logger.addHandler(file_handler)
    logger.addHandler(stderr_handler)


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------


def read_input() -> dict:
    """Read JSON input from stdin."""
    raw = sys.stdin.read()
    logger.debug("Raw input: %s", raw)
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Create or re-enter a worktree from the JSON request on stdin."""
    setup_logging()
    logger.info("WorktreeCreate hook invoked")

    try:
        data = read_input()
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to read input: %s", e)
        return 1

    name = data.get("name", "")
    cwd = data.get("cwd", "")
    session_id = data.get("session_id", "")

    logger.info("name=%s cwd=%s session_id=%s", name, cwd, session_id)
    logger.debug("Full input: %s", json.dumps(data, indent=2))

    if not name:
        logger.error("No name provided")
        return 1

    # Find the main repo root (resolves correctly even from inside a worktree)
    repo_root = find_main_repo_root(cwd)
    if repo_root is None:
        logger.error("Not in a git repository: %s", cwd)
        return 1

    logger.info("Repo root: %s", repo_root)

    # Load config and build prefix map
    config = load_config(repo_root)
    prefix_map = build_prefix_map(config)

    # Parse the name into branch and directory names
    branch_name, dir_name = parse_name(name, prefix_map)

    # Caveat: if a branch with the *literal* requested name already exists
    # (e.g. a worktree created before normalisation, in the old flat format),
    # honour it as-is rather than normalising to the nested form and forking
    # a second, divergent branch.
    if name != branch_name and branch_exists_local(repo_root, name):
        logger.info(
            "Literal branch %r exists; honouring it instead of normalised %r",
            name,
            branch_name,
        )
        branch_name, dir_name = name, name

    # Resolve where worktrees live. Default is the native .claude/worktrees
    # path; sibling and custom in-repo layouts are opt-in via config.
    work_base, exclude_rel = resolve_work_base(repo_root, config)
    worktree_path = work_base / dir_name

    # Keep in-repo worktrees out of the main repo's git status.
    if exclude_rel is not None:
        ensure_excluded(repo_root, exclude_rel)

    logger.info("Branch: %s", branch_name)
    logger.info("Worktree path: %s", worktree_path)

    # Re-entrant: check if any worktree already has this branch checked out
    existing = find_worktree_for_branch(repo_root, branch_name)
    if existing is not None:
        if existing != worktree_path:
            logger.info(
                "Branch %r already checked out at %s (not our expected %s), using existing",
                branch_name,
                existing,
                worktree_path,
            )
        else:
            logger.info("Worktree already exists at expected path, re-entering")
        print(str(existing))
        return 0

    # If the directory exists but isn't a registered worktree, don't clobber it
    if worktree_path.exists():
        logger.error("Directory exists but is not a registered worktree: %s", worktree_path)
        return 1

    # Create the work base directory if needed
    work_base.mkdir(parents=True, exist_ok=True)

    # Determine the default branch for this repo
    default_branch = get_default_branch(repo_root)

    # Create the worktree — check local, then remote, then create fresh
    if branch_exists_local(repo_root, branch_name):
        logger.info("Local branch %r exists, checking out into worktree", branch_name)
        result = git(
            "worktree",
            "add",
            str(worktree_path),
            branch_name,
            cwd=str(repo_root),
        )
    elif branch_exists_remote(repo_root, branch_name):
        logger.info(
            "Remote branch %r found, creating local tracking branch",
            branch_name,
        )
        result = git(
            "worktree",
            "add",
            str(worktree_path),
            "-b",
            branch_name,
            f"origin/{branch_name}",
            cwd=str(repo_root),
        )
    else:
        # Branch fresh work from origin/<default> when a remote tracking ref
        # exists, so new branches don't inherit a stale local default branch.
        # Fall back to the local default branch for repos with no remote.
        if branch_exists_remote(repo_root, default_branch):
            base_ref = f"origin/{default_branch}"
        else:
            base_ref = default_branch
        logger.info(
            "Creating new branch %r from %s",
            branch_name,
            base_ref,
        )
        result = git(
            "worktree",
            "add",
            str(worktree_path),
            "-b",
            branch_name,
            base_ref,
            cwd=str(repo_root),
        )

    if result.returncode != 0:
        logger.error("Failed to create worktree: %s", result.stderr.strip())
        return 1

    logger.info("Created worktree at: %s", worktree_path)
    print(str(worktree_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
