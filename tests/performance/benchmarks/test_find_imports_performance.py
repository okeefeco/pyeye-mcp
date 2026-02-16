"""Performance tests for the find_imports optimization."""

import time

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from tests.utils.performance import (
    PerformanceThresholds,
    assert_performance_threshold,
)


class TestFindImportsPerformance:
    """Test performance improvements for find_imports method."""

    @pytest.fixture
    async def test_project(self, tmp_path):
        """Create a test project with many files."""
        # Create a project with 50 Python files
        for i in range(50):
            module_dir = tmp_path / f"module_{i}"
            module_dir.mkdir()

            # Create __init__.py
            (module_dir / "__init__.py").write_text("")

            # Create a module file with various imports
            module_file = module_dir / f"file_{i}.py"
            content = f'''"""Module {i}."""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List

# Only a few files import our target module
'''
            if i % 10 == 0:  # Only 10% of files import the target
                content += """import target_module
from target_module import something
"""

            module_file.write_text(content)

        # Create the target module
        target_dir = tmp_path / "target_module"
        target_dir.mkdir()
        (target_dir / "__init__.py").write_text('"""Target module."""\n\ndef something(): pass')

        return tmp_path

    @pytest.mark.asyncio
    async def test_find_imports_performance(self, test_project):
        """Test that find_imports performs well with many files."""
        analyzer = JediAnalyzer(test_project)

        # Warm up the cache
        await analyzer.find_imports("os", scope="main")

        # Measure performance for finding imports
        start_time = time.perf_counter()
        results = await analyzer.find_imports("target_module", scope="main")
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Should find imports in the 5 files that import target_module
        assert len(results) > 0

        # Define performance threshold for find_imports
        # With ripgrep optimization, should be much faster than scanning all files
        find_imports_threshold = PerformanceThresholds(
            base=500.0,  # 500ms for local development (50 files)
            linux_ci=750.0,  # 750ms for Linux CI
            macos_ci=1500.0,  # 1.5s for macOS CI
            windows_ci=1500.0,  # 1.5s for Windows CI
        )

        assert_performance_threshold(
            elapsed_ms, find_imports_threshold, "find_imports with 50 files"
        )

    @pytest.mark.asyncio
    async def test_find_imports_cache_performance(self, test_project):
        """Test that cached find_imports is very fast."""
        analyzer = JediAnalyzer(test_project)

        # First call to populate cache
        await analyzer.find_imports("target_module", scope="main")

        # Second call should be cached
        start_time = time.perf_counter()
        await analyzer.find_imports("target_module", scope="main")
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Cached call should be very fast
        cache_threshold = PerformanceThresholds(
            base=10.0,  # 10ms for local development
            linux_ci=15.0,  # 15ms for Linux CI
            macos_ci=30.0,  # 30ms for macOS CI
            windows_ci=30.0,  # 30ms for Windows CI
        )

        assert_performance_threshold(elapsed_ms, cache_threshold, "find_imports cached")

    @pytest.mark.asyncio
    async def test_find_imports_no_matches_performance(self, test_project):
        """Test performance when no imports are found."""
        analyzer = JediAnalyzer(test_project)

        # Search for a module that doesn't exist
        start_time = time.perf_counter()
        results = await analyzer.find_imports("nonexistent_module", scope="main")
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        assert len(results) == 0

        # With ripgrep, no-match case should be very fast
        # Threshold increased to account for regex escaping overhead and filesystem I/O variability
        # Issue #283: Additional relative import patterns slightly increase search time
        # CI environments have high variability - thresholds set with ~25% headroom
        no_match_threshold = PerformanceThresholds(
            base=400.0,  # 400ms for local development
            linux_ci=800.0,  # 800ms for Linux CI (high variability)
            macos_ci=900.0,  # 900ms for macOS CI
            windows_ci=1500.0,  # 1500ms for Windows CI (highest variability)
        )

        assert_performance_threshold(elapsed_ms, no_match_threshold, "find_imports no matches")

    @pytest.mark.asyncio
    async def test_find_imports_large_project_simulation(self, tmp_path):
        """Test performance with a larger project (200 files)."""
        # Create a larger project
        for i in range(200):
            module_file = tmp_path / f"module_{i}.py"
            content = f'''"""Module {i}."""
import os
import sys
'''
            if i < 10:  # Only first 10 files import the target
                content += "import large_target\n"

            module_file.write_text(content)

        analyzer = JediAnalyzer(tmp_path)

        # Measure performance
        start_time = time.perf_counter()
        await analyzer.find_imports("large_target", scope="main")
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Large project threshold
        large_project_threshold = PerformanceThresholds(
            base=1000.0,  # 1s for local development (200 files)
            linux_ci=1500.0,  # 1.5s for Linux CI
            macos_ci=3000.0,  # 3s for macOS CI
            windows_ci=3000.0,  # 3s for Windows CI
        )

        assert_performance_threshold(
            elapsed_ms, large_project_threshold, "find_imports with 200 files"
        )

    @pytest.mark.asyncio
    async def test_default_scope_performance(self, test_project):
        """Test that default scope (main) is performant."""
        analyzer = JediAnalyzer(test_project)

        # Call without specifying scope (should default to "main" now)
        start_time = time.perf_counter()
        await analyzer.find_imports("target_module")
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Default scope should be fast
        # Issue #283: Additional relative import patterns slightly increase search time
        default_scope_threshold = PerformanceThresholds(
            base=600.0,  # 600ms for local development (increased for relative import patterns)
            linux_ci=850.0,  # 850ms for Linux CI (increased for relative import patterns)
            macos_ci=1600.0,  # 1.6s for macOS CI
            windows_ci=1600.0,  # 1.6s for Windows CI
        )

        assert_performance_threshold(
            elapsed_ms, default_scope_threshold, "find_imports default scope"
        )
