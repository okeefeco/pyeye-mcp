"""Tests for dependency tracking."""

from pathlib import Path

import pytest
from pycodemcp.dependency_tracker import DependencyTracker


class TestDependencyTracker:
    """Test suite for DependencyTracker."""

    @pytest.fixture
    def tracker(self):
        """Create a fresh dependency tracker."""
        return DependencyTracker()

    def test_init(self, tracker):
        """Test tracker initialization."""
        assert tracker.imports == {}
        assert tracker.imported_by == {}
        assert tracker.file_to_module == {}
        assert tracker.module_to_file == {}
        assert tracker.symbol_definitions == {}
        assert tracker.symbol_imports == {}

    def test_add_import(self, tracker):
        """Test adding import relationships."""
        tracker.add_import("module_a", "module_b")

        assert "module_b" in tracker.imports["module_a"]
        assert "module_a" in tracker.imported_by["module_b"]

        # Test multiple imports
        tracker.add_import("module_a", "module_c")
        tracker.add_import("module_c", "module_b")

        assert len(tracker.imports["module_a"]) == 2
        assert "module_c" in tracker.imports["module_a"]
        assert len(tracker.imported_by["module_b"]) == 2

    def test_add_file_mapping(self, tracker):
        """Test file to module mapping."""
        file_path = Path("/project/src/module.py")
        tracker.add_file_mapping(file_path, "src.module")

        assert tracker.file_to_module[file_path.resolve()] == "src.module"
        assert tracker.module_to_file["src.module"] == file_path.resolve()

        # Test multiple files
        file2 = Path("/project/src/utils.py")
        tracker.add_file_mapping(file2, "src.utils")

        assert len(tracker.file_to_module) == 2
        assert len(tracker.module_to_file) == 2

    def test_add_symbol_definition(self, tracker):
        """Test tracking symbol definitions."""
        tracker.add_symbol_definition("module_a", "ClassA")
        tracker.add_symbol_definition("module_a", "function_a")
        tracker.add_symbol_definition("module_b", "ClassB")

        assert "ClassA" in tracker.symbol_definitions["module_a"]
        assert "function_a" in tracker.symbol_definitions["module_a"]
        assert "ClassB" in tracker.symbol_definitions["module_b"]
        assert len(tracker.symbol_definitions["module_a"]) == 2

    def test_add_symbol_import(self, tracker):
        """Test tracking symbol-level imports."""
        tracker.add_symbol_import("module_a", "module_b", "ClassB")

        assert "ClassB" in tracker.symbol_imports["module_a"]["module_b"]
        assert "module_b" in tracker.imports["module_a"]
        assert "module_a" in tracker.imported_by["module_b"]

        # Test multiple symbol imports
        tracker.add_symbol_import("module_a", "module_b", "function_b")
        tracker.add_symbol_import("module_a", "module_c", "ClassC")

        assert len(tracker.symbol_imports["module_a"]["module_b"]) == 2
        assert "module_c" in tracker.symbol_imports["module_a"]

    def test_get_dependents(self, tracker):
        """Test getting modules that depend on a given module."""
        tracker.add_import("module_a", "module_core")
        tracker.add_import("module_b", "module_core")
        tracker.add_import("module_c", "module_a")

        dependents = tracker.get_dependents("module_core")
        assert "module_a" in dependents
        assert "module_b" in dependents
        assert "module_c" not in dependents

        # Test module with no dependents
        assert tracker.get_dependents("module_c") == set()

        # Test non-existent module
        assert tracker.get_dependents("module_unknown") == set()

    def test_get_dependencies(self, tracker):
        """Test getting modules that a given module depends on."""
        tracker.add_import("module_a", "module_b")
        tracker.add_import("module_a", "module_c")
        tracker.add_import("module_b", "module_d")

        deps = tracker.get_dependencies("module_a")
        assert "module_b" in deps
        assert "module_c" in deps
        assert "module_d" not in deps

        # Test module with no dependencies
        assert tracker.get_dependencies("module_d") == set()

        # Test non-existent module
        assert tracker.get_dependencies("module_unknown") == set()

    def test_get_affected_modules(self, tracker):
        """Test getting modules affected by file changes."""
        # Set up file mappings and dependencies
        file1 = Path("/project/core.py")
        file2 = Path("/project/utils.py")
        file3 = Path("/project/main.py")

        tracker.add_file_mapping(file1, "core")
        tracker.add_file_mapping(file2, "utils")
        tracker.add_file_mapping(file3, "main")

        tracker.add_import("utils", "core")
        tracker.add_import("main", "utils")
        tracker.add_import("main", "core")

        # Test changes to core affect both utils and main
        affected = tracker.get_affected_modules(file1)
        assert "core" in affected  # The module itself
        assert "utils" in affected  # Direct dependent
        assert "main" in affected  # Also imports core

        # Test changes to utils affect main
        affected = tracker.get_affected_modules(file2)
        assert "utils" in affected
        assert "main" in affected
        assert "core" not in affected

        # Test file with no dependents
        affected = tracker.get_affected_modules(file3)
        assert affected == {"main"}

        # Test unknown file
        unknown_file = Path("/project/unknown.py")
        affected = tracker.get_affected_modules(unknown_file)
        assert affected == set()

    def test_get_affected_symbols(self, tracker):
        """Test getting symbols affected by changes."""
        # Set up symbol definitions and imports
        tracker.add_symbol_definition("module_a", "ClassA")
        tracker.add_symbol_definition("module_a", "function_a")
        tracker.add_symbol_definition("module_b", "ClassB")

        tracker.add_symbol_import("module_b", "module_a", "ClassA")
        tracker.add_symbol_import("module_c", "module_a", "ClassA")
        tracker.add_symbol_import("module_c", "module_a", "function_a")

        # Test specific symbol changes
        affected = tracker.get_affected_symbols("module_a", {"ClassA"})
        assert "ClassA" in affected["module_b"]
        assert "ClassA" in affected["module_c"]
        assert "function_a" not in affected["module_c"]

        # Test all symbols changed (None)
        affected = tracker.get_affected_symbols("module_a", None)
        assert "ClassA" in affected["module_b"]
        assert "ClassA" in affected["module_c"]
        assert "function_a" in affected["module_c"]

        # Test no affected symbols
        affected = tracker.get_affected_symbols("module_b", {"ClassB"})
        assert affected == {}

    def test_clear(self, tracker):
        """Test clearing all tracking data."""
        # Add some data
        tracker.add_import("module_a", "module_b")
        tracker.add_file_mapping(Path("/test.py"), "test")
        tracker.add_symbol_definition("module_a", "ClassA")
        tracker.add_symbol_import("module_b", "module_a", "ClassA")

        # Clear everything
        tracker.clear()

        assert tracker.imports == {}
        assert tracker.imported_by == {}
        assert tracker.file_to_module == {}
        assert tracker.module_to_file == {}
        assert tracker.symbol_definitions == {}
        assert tracker.symbol_imports == {}

    def test_get_stats(self, tracker):
        """Test getting dependency statistics."""
        # Empty tracker
        stats = tracker.get_stats()
        assert stats["total_modules"] == 0
        assert stats["modules_with_imports"] == 0
        assert stats["modules_imported"] == 0
        assert stats["total_import_edges"] == 0
        assert stats["total_symbols_tracked"] == 0
        assert stats["max_dependencies"] == 0
        assert stats["max_dependents"] == 0

        # Add some data
        tracker.add_file_mapping(Path("/a.py"), "module_a")
        tracker.add_file_mapping(Path("/b.py"), "module_b")
        tracker.add_file_mapping(Path("/c.py"), "module_c")

        tracker.add_import("module_a", "module_b")
        tracker.add_import("module_a", "module_c")
        tracker.add_import("module_b", "module_c")

        tracker.add_symbol_definition("module_a", "ClassA")
        tracker.add_symbol_definition("module_a", "function_a")
        tracker.add_symbol_definition("module_b", "ClassB")

        stats = tracker.get_stats()
        assert stats["total_modules"] == 3
        assert stats["modules_with_imports"] == 2
        assert stats["modules_imported"] == 2
        assert stats["total_import_edges"] == 3
        assert stats["total_symbols_tracked"] == 3
        assert stats["max_dependencies"] == 2  # module_a imports 2 modules
        assert stats["max_dependents"] == 2  # module_c is imported by 2 modules

    def test_complex_dependency_graph(self, tracker):
        """Test with a more complex dependency structure."""
        # Create a diamond dependency:
        #     A
        #    / \
        #   B   C
        #    \ /
        #     D

        files = {
            "a": Path("/project/a.py"),
            "b": Path("/project/b.py"),
            "c": Path("/project/c.py"),
            "d": Path("/project/d.py"),
        }

        for name, path in files.items():
            tracker.add_file_mapping(path, f"module_{name}")

        tracker.add_import("module_a", "module_b")
        tracker.add_import("module_a", "module_c")
        tracker.add_import("module_b", "module_d")
        tracker.add_import("module_c", "module_d")

        # Changes to D affect B, C, and A
        affected = tracker.get_affected_modules(files["d"])
        assert len(affected) == 3
        assert "module_d" in affected
        assert "module_b" in affected
        assert "module_c" in affected

        # Changes to B affect only A
        affected = tracker.get_affected_modules(files["b"])
        assert len(affected) == 2
        assert "module_b" in affected
        assert "module_a" in affected

        # Changes to A affect nothing else
        affected = tracker.get_affected_modules(files["a"])
        assert affected == {"module_a"}

    def test_circular_dependencies(self, tracker):
        """Test handling of circular dependencies."""
        # Create circular dependency: A -> B -> C -> A
        files = {
            "a": Path("/project/a.py"),
            "b": Path("/project/b.py"),
            "c": Path("/project/c.py"),
        }

        for name, path in files.items():
            tracker.add_file_mapping(path, f"module_{name}")

        tracker.add_import("module_a", "module_b")
        tracker.add_import("module_b", "module_c")
        tracker.add_import("module_c", "module_a")

        # Each module should show the others as affected
        affected = tracker.get_affected_modules(files["a"])
        assert "module_a" in affected
        assert "module_c" in affected  # C imports A

        affected = tracker.get_affected_modules(files["b"])
        assert "module_b" in affected
        assert "module_a" in affected  # A imports B

        affected = tracker.get_affected_modules(files["c"])
        assert "module_c" in affected
        assert "module_b" in affected  # B imports C
