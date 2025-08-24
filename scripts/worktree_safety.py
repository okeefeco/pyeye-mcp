#!/usr/bin/env python3
"""Worktree safety utilities to prevent accidental data loss."""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def run_git_command(args: list[str]) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    return subprocess.run(["git"] + args, capture_output=True, text=True, check=False)


def check_worktree_status(worktree_path: str) -> dict[str, Any]:
    """Check if worktree has uncommitted changes."""
    result = run_git_command(["-C", worktree_path, "status", "--porcelain"])

    if result.returncode != 0:
        return {"path": worktree_path, "accessible": False, "error": result.stderr.strip()}

    changes = result.stdout.strip()
    has_changes = len(changes) > 0

    # Count different types of changes
    modified = len(
        [line for line in changes.split("\n") if line.startswith(" M") or line.startswith("M ")]
    )
    added = len(
        [line for line in changes.split("\n") if line.startswith("A ") or line.startswith("??")]
    )
    deleted = len(
        [line for line in changes.split("\n") if line.startswith(" D") or line.startswith("D ")]
    )

    return {
        "path": worktree_path,
        "accessible": True,
        "has_changes": has_changes,
        "changes": changes,
        "stats": {
            "modified": modified,
            "added": added,
            "deleted": deleted,
            "total": len(changes.split("\n")) if changes else 0,
        },
    }


def list_worktrees() -> list[dict[str, str]]:
    """List all git worktrees with their details."""
    result = run_git_command(["worktree", "list", "--porcelain"])

    if result.returncode != 0:
        print(f"Error listing worktrees: {result.stderr}", file=sys.stderr)
        return []

    worktrees = []
    current_worktree: dict[str, Any] = {}

    for line in result.stdout.strip().split("\n"):
        if line.startswith("worktree "):
            if current_worktree:
                worktrees.append(current_worktree)
            current_worktree = {"path": line.replace("worktree ", "")}
        elif line.startswith("HEAD "):
            current_worktree["head"] = line.replace("HEAD ", "")
        elif line.startswith("branch "):
            current_worktree["branch"] = line.replace("branch refs/heads/", "")
        elif line.startswith("detached"):
            current_worktree["detached"] = True

    if current_worktree:
        worktrees.append(current_worktree)

    return worktrees


def list_safe_worktrees() -> tuple[list[dict], list[dict]]:
    """List worktrees that are safe to remove (no uncommitted changes)."""
    worktrees = list_worktrees()
    safe = []
    unsafe = []

    # Get current directory to avoid removing active worktree
    current_dir = Path.cwd().resolve()

    for worktree in worktrees:
        path = Path(worktree["path"]).resolve()

        # Skip the current worktree
        if path == current_dir or current_dir.is_relative_to(path):
            print(f"⏭️  Skipping current worktree: {worktree['path']}")
            continue

        status = check_worktree_status(worktree["path"])
        worktree.update(status)

        if not status["accessible"] or status["has_changes"]:
            unsafe.append(worktree)
        else:
            safe.append(worktree)

    return safe, unsafe


def safe_remove_worktree(worktree_path: str, force: bool = False) -> bool:
    """Safely remove a worktree with confirmation."""
    status = check_worktree_status(worktree_path)

    if not status["accessible"]:
        print(f"⚠️  Cannot access worktree: {worktree_path}")
        print(f"   Error: {status.get('error', 'Unknown error')}")
        if not force:
            return False

    if status.get("has_changes"):
        print(f"⚠️  {worktree_path} has uncommitted changes!")
        print(f"   Modified: {status['stats']['modified']} files")
        print(f"   Added: {status['stats']['added']} files")
        print(f"   Deleted: {status['stats']['deleted']} files")

        if not force:
            response = input("\nDo you really want to force remove? (type 'FORCE' to confirm): ")
            if response != "FORCE":
                print("Aborted.")
                return False

    # Perform removal
    args = ["worktree", "remove", worktree_path]
    if force:
        args.append("--force")

    result = run_git_command(args)

    if result.returncode == 0:
        print(f"✅ Successfully removed worktree: {worktree_path}")
        return True
    else:
        print(f"❌ Failed to remove worktree: {result.stderr}", file=sys.stderr)
        return False


def load_ownership_data() -> dict[str, Any]:
    """Load worktree ownership data if it exists."""
    ownership_file = Path(".worktree-ownership.json")
    if ownership_file.exists():
        try:
            data: dict[str, Any] = json.loads(ownership_file.read_text())
            return data
        except (OSError, json.JSONDecodeError):
            return {"worktrees": {}}
    return {"worktrees": {}}


def save_ownership_data(data: dict[str, Any]) -> None:
    """Save worktree ownership data."""
    ownership_file = Path(".worktree-ownership.json")
    ownership_file.write_text(json.dumps(data, indent=2))


def track_worktree_creation(worktree_path: str, branch: str, purpose: str = "") -> None:
    """Track the creation of a new worktree."""
    data = load_ownership_data()

    worktree_name = Path(worktree_path).name
    data["worktrees"][worktree_name] = {
        "path": str(worktree_path),
        "branch": branch,
        "created_at": datetime.now().isoformat(),
        "purpose": purpose,
        "session_id": f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
    }

    save_ownership_data(data)
    print(f"📝 Tracked worktree creation: {worktree_name}")


def check_ownership(worktree_path: str, session_id: str | None = None) -> bool:
    """Check if a worktree belongs to the current session."""
    data = load_ownership_data()
    worktree_name = Path(worktree_path).name

    if worktree_name not in data["worktrees"]:
        return False  # Not tracked, assume not owned

    worktree_info = data["worktrees"][worktree_name]

    if session_id and worktree_info.get("session_id") == session_id:
        return True

    # Check if created recently (within last hour)
    created_at = datetime.fromisoformat(worktree_info["created_at"])
    age_hours = (datetime.now() - created_at).total_seconds() / 3600

    return age_hours < 1  # Only claim ownership if created within last hour


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Git worktree safety utilities")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # List command
    list_parser = subparsers.add_parser("list", help="List all worktrees with safety status")
    list_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # Check command
    check_parser = subparsers.add_parser("check", help="Check status of a specific worktree")
    check_parser.add_argument("path", help="Path to the worktree")

    # Remove command
    remove_parser = subparsers.add_parser("remove", help="Safely remove a worktree")
    remove_parser.add_argument("path", help="Path to the worktree")
    remove_parser.add_argument(
        "--force", action="store_true", help="Force removal even with changes"
    )

    # Clean command
    clean_parser = subparsers.add_parser("clean", help="Remove all safe worktrees")
    clean_parser.add_argument("--dry-run", action="store_true", help="Show what would be removed")

    # Track command
    track_parser = subparsers.add_parser("track", help="Track creation of a worktree")
    track_parser.add_argument("path", help="Path to the worktree")
    track_parser.add_argument("branch", help="Branch name")
    track_parser.add_argument("--purpose", help="Purpose of the worktree")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "list":
        safe, unsafe = list_safe_worktrees()

        if args.json:
            print(json.dumps({"safe": safe, "unsafe": unsafe}, indent=2))
        else:
            print("🌳 Git Worktrees Safety Report")
            print("=" * 60)

            if unsafe:
                print("\n⚠️  UNSAFE to remove (have uncommitted changes):")
                for wt in unsafe:
                    branch = wt.get("branch", "detached")
                    if wt.get("accessible", True):
                        print(f"  - {wt['path']} [{branch}]")
                        if wt.get("has_changes"):
                            stats = wt.get("stats", {})
                            print(
                                f"    Changes: {stats.get('modified', 0)}M, {stats.get('added', 0)}A, {stats.get('deleted', 0)}D"
                            )
                    else:
                        print(f"  - {wt['path']} [INACCESSIBLE]")

            if safe:
                print("\n✅ SAFE to remove (no uncommitted changes):")
                for wt in safe:
                    branch = wt.get("branch", "detached")
                    print(f"  - {wt['path']} [{branch}]")

            if not safe and not unsafe:
                print("\nNo worktrees found (other than current).")

            print("\n" + "=" * 60)
            print(f"Summary: {len(safe)} safe, {len(unsafe)} unsafe")

    elif args.command == "check":
        status = check_worktree_status(args.path)
        if status["accessible"]:
            if status["has_changes"]:
                print("⚠️  Worktree has uncommitted changes")
                print(f"   Modified: {status['stats']['modified']} files")
                print(f"   Added: {status['stats']['added']} files")
                print(f"   Deleted: {status['stats']['deleted']} files")
                return 1
            else:
                print("✅ Worktree is clean (safe to remove)")
                return 0
        else:
            print(f"❌ Cannot access worktree: {status.get('error', 'Unknown error')}")
            return 1

    elif args.command == "remove":
        success = safe_remove_worktree(args.path, args.force)
        return 0 if success else 1

    elif args.command == "clean":
        safe, _ = list_safe_worktrees()

        if not safe:
            print("No safe worktrees to remove.")
            return 0

        print(f"Found {len(safe)} worktree(s) safe to remove:")
        for wt in safe:
            print(f"  - {wt['path']}")

        if args.dry_run:
            print("\n(Dry run - no changes made)")
            return 0

        response = input(f"\nRemove {len(safe)} worktree(s)? (y/N): ")
        if response.lower() != "y":
            print("Aborted.")
            return 1

        removed = 0
        for wt in safe:
            if safe_remove_worktree(wt["path"]):
                removed += 1

        print(f"\nRemoved {removed} worktree(s).")

    elif args.command == "track":
        track_worktree_creation(args.path, args.branch, args.purpose or "")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
