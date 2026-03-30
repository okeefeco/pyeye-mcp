#!/usr/bin/env python3
"""Test script for cross-platform validator agent.

This script creates sample files with common path issues that the agent should detect and fix.
"""

import tempfile
from pathlib import Path


def create_test_files() -> Path:
    """Create test files with various path issues."""
    test_dir = Path(tempfile.mkdtemp(prefix="cross_platform_test_"))
    print(f"Created test directory: {test_dir}")

    # Test file 1: API response with str(Path)
    api_file = test_dir / "api_handler.py"
    api_file.write_text('''from pathlib import Path

def get_file_info(file_path: Path):
    """Return file information for API response."""
    return {
        "path": str(file_path),  # Should be file_path.as_posix()
        "name": file_path.name,
        "parent": str(file_path.parent),  # Should be file_path.parent.as_posix()
    }

def get_template_path(template_name: str, template_dir: Path):
    """Get template path for rendering."""
    template_file = template_dir / template_name
    # This will break on Windows
    return str(template_file.relative_to(template_dir))  # Should use .as_posix()
''')
    print(f"Created API handler with path issues: {api_file}")

    # Test file 2: Cache with direct string conversion
    cache_file = test_dir / "cache_manager.py"
    cache_file.write_text('''from pathlib import Path
from typing import Dict, Any

class CacheManager:
    def __init__(self):
        self.cache: Dict[str, Any] = {}

    def get(self, file_path: Path) -> Any:
        """Get cached value for file."""
        # Direct string conversion for dict key - problematic
        return self.cache.get(str(file_path))  # Should use path_to_key()

    def set(self, file_path: Path, value: Any) -> None:
        """Set cached value for file."""
        # Another direct conversion
        self.cache[str(file_path)] = value  # Should use path_to_key()

    def has_file(self, path1: Path, path2: Path) -> bool:
        """Check if two paths are the same."""
        # Direct string comparison
        return str(path1) == str(path2)  # Should use paths_equal()
''')
    print(f"Created cache manager with path issues: {cache_file}")

    # Test file 3: Config handling
    config_file = test_dir / "config.py"
    config_file.write_text('''from pathlib import Path
import json

def save_config(config_path: Path, settings: dict):
    """Save configuration to file."""
    # Add project paths to config
    settings["project_root"] = str(Path.cwd())  # Should be Path.cwd().as_posix()
    settings["data_dir"] = str(Path("data"))  # Should be Path("data").as_posix()

    with open(config_path, "w") as f:
        json.dump(settings, f)

def load_paths_from_config(config: dict) -> list:
    """Load paths from configuration."""
    paths = []
    for path_str in config.get("include_paths", []):
        # Creating Path from potentially Windows-style string
        paths.append(Path(path_str))  # May have backslashes from Windows
    return paths
''')
    print(f"Created config handler with path issues: {config_file}")

    # Test file 4: Mixed contexts (some correct, some not)
    mixed_file = test_dir / "mixed_usage.py"
    mixed_file.write_text('''from pathlib import Path
import subprocess
import os

def process_file(file_path: Path):
    """Process file with mixed path usage."""
    # Correct: OS operation
    if os.path.exists(str(file_path)):
        # Incorrect: Display context
        print(f"Processing: {str(file_path)}")  # Should be file_path.as_posix()

        # Correct: subprocess needs str
        result = subprocess.run(["cat", str(file_path)], capture_output=True)

        # Incorrect: Return for API
        return {
            "file": str(file_path),  # Should be file_path.as_posix()
            "exists": True,
            "size": os.path.getsize(str(file_path))  # This is OK (OS operation)
        }

    return {"file": str(file_path), "exists": False}  # Should be as_posix()
''')
    print(f"Created mixed usage file: {mixed_file}")

    return test_dir


def main() -> None:
    """Run test setup."""
    print("Setting up test files for cross-platform validator agent...")
    print("=" * 60)

    test_dir = create_test_files()

    print("=" * 60)
    print("\nTest files created successfully!")
    print("\nTo test the agent, run in Claude Code:")
    print("1. Use the Task tool with subagent_type='cross-platform-validator'")
    print("2. Or use /agents and select 'cross-platform-validator'")
    print(f"3. Ask it to: 'Check cross-platform compatibility in {test_dir}'")
    print("\nThe agent should find and fix:")
    print("  - str(Path) usage in API responses")
    print("  - Direct path comparisons")
    print("  - Path dictionary keys without path_to_key()")
    print("  - Config paths without .as_posix()")
    print("\nExpected: 10+ issues across 4 files")


if __name__ == "__main__":
    main()
