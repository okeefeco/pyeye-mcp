"""Performance benchmarks for smart cache invalidation."""

import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

from pycodemcp.cache import GranularCache, ProjectCache
from pycodemcp.import_analyzer import ImportAnalyzer
from tests.utils.performance import (
    get_ci_tolerance_factor,
    get_platform_name,
    is_ci_environment,
)


class TestPerformanceBenchmarks:
    """Performance benchmarks comparing traditional vs smart invalidation."""

    @pytest.fixture
    def large_project(self):
        """Create a large project structure for benchmarking."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)

            # Create a large project structure
            # Simulating a project with 100 modules in 10 packages
            for pkg_num in range(10):
                pkg_dir = project_path / f"package_{pkg_num}"
                pkg_dir.mkdir()
                (pkg_dir / "__init__.py").write_text("")

                for mod_num in range(10):
                    module_content = f"""
# Module {pkg_num}.{mod_num}

class Class_{pkg_num}_{mod_num}:
    pass

def function_{pkg_num}_{mod_num}():
    pass
"""
                    # Add imports to create dependencies
                    if pkg_num > 0:
                        # Import from previous package
                        module_content = (
                            f"from package_{pkg_num-1}.module_0 import Class_{pkg_num-1}_0\n"
                            + module_content
                        )

                    if mod_num > 0:
                        # Import from previous module in same package
                        module_content = (
                            f"from .module_{mod_num-1} import function_{pkg_num}_{mod_num-1}\n"
                            + module_content
                        )

                    (pkg_dir / f"module_{mod_num}.py").write_text(module_content)

            yield project_path

    def benchmark_traditional_invalidation(
        self, _project_path: Path, num_changes: int = 10
    ) -> dict[str, Any]:
        """Benchmark traditional cache invalidation (invalidate all)."""
        cache = ProjectCache()

        # Populate cache with many entries
        start_populate = time.perf_counter()
        for i in range(1000):
            cache.set(f"key_{i}", f"value_{i}")
        populate_time = time.perf_counter() - start_populate

        # Simulate file changes and measure invalidation time
        invalidation_times = []
        cache_misses = 0

        for _change_num in range(num_changes):
            # Measure invalidation time
            start_invalidate = time.perf_counter()
            cache.invalidate()  # Traditional: invalidate everything
            invalidation_time = time.perf_counter() - start_invalidate
            invalidation_times.append(invalidation_time)

            # Repopulate some entries (simulating re-analysis)
            for i in range(100):  # Repopulate 10% of entries
                cache.set(f"key_{i}", f"value_{i}_new")

            # Simulate cache access
            for i in range(50):
                if cache.get(f"key_{i}") is None:
                    cache_misses += 1

        return {
            "populate_time": populate_time,
            "avg_invalidation_time": sum(invalidation_times) / len(invalidation_times),
            "total_invalidation_time": sum(invalidation_times),
            "cache_misses": cache_misses,
            "entries_invalidated_per_change": 1000,  # Always invalidates all
        }

    def benchmark_smart_invalidation(
        self, project_path: Path, num_changes: int = 10
    ) -> dict[str, Any]:
        """Benchmark smart cache invalidation."""
        cache = GranularCache()

        # Build dependency graph
        analyzer = ImportAnalyzer(project_path)
        python_files = list(project_path.rglob("*.py"))
        graph = analyzer.build_dependency_graph(python_files)

        # Populate dependency tracker
        for module_name, file_path in graph["modules"].items():
            cache.dependency_tracker.add_file_mapping(Path(file_path), module_name)

            if module_name in graph["imports"]:
                for imported in graph["imports"][module_name]:
                    if imported in graph["modules"]:
                        cache.dependency_tracker.add_import(module_name, imported)

        # Populate cache with many entries
        start_populate = time.perf_counter()
        for file_index, i in enumerate(range(1000)):
            # Associate entries with different files
            file_path = python_files[file_index % len(python_files)]
            module_name = cache.dependency_tracker.file_to_module.get(file_path)
            cache.set(f"key_{i}", f"value_{i}", file_path=file_path, module_name=module_name)
        populate_time = time.perf_counter() - start_populate

        # Simulate file changes and measure invalidation time
        invalidation_times = []
        entries_invalidated = []
        cache_misses = 0

        for change_num in range(num_changes):
            # Pick a file to change
            changed_file = python_files[change_num % len(python_files)]

            # Measure invalidation time
            start_invalidate = time.perf_counter()
            count = cache.invalidate_file(changed_file)
            invalidation_time = time.perf_counter() - start_invalidate
            invalidation_times.append(invalidation_time)
            entries_invalidated.append(count)

            # Repopulate invalidated entries (simulating re-analysis)
            module_name = cache.dependency_tracker.file_to_module.get(changed_file)
            if module_name:
                for i in range(min(10, count)):  # Repopulate some entries
                    cache.set(
                        f"key_{change_num}_{i}",
                        "value_new",
                        file_path=changed_file,
                        module_name=module_name,
                    )

            # Simulate cache access
            for i in range(50):
                if cache.get(f"key_{i}") is None:
                    cache_misses += 1

        metrics = cache.get_metrics()

        return {
            "populate_time": populate_time,
            "avg_invalidation_time": sum(invalidation_times) / len(invalidation_times),
            "total_invalidation_time": sum(invalidation_times),
            "cache_misses": cache_misses,
            "entries_invalidated_per_change": sum(entries_invalidated) / len(entries_invalidated),
            "cache_hit_rate": metrics["cache"]["hit_rate"],
            "total_invalidations": metrics["cache"]["invalidations"]["total"],
        }

    def test_invalidation_performance_comparison(self, large_project):
        """Compare performance between traditional and smart invalidation."""
        # Run benchmarks
        traditional_results = self.benchmark_traditional_invalidation(large_project)
        smart_results = self.benchmark_smart_invalidation(large_project)

        # Print results for visibility
        print("\n=== Performance Benchmark Results ===")
        print("\nTraditional Invalidation:")
        print(f"  Avg invalidation time: {traditional_results['avg_invalidation_time']:.4f}s")
        print(
            f"  Entries invalidated per change: {traditional_results['entries_invalidated_per_change']}"
        )
        print(f"  Cache misses: {traditional_results['cache_misses']}")

        print("\nSmart Invalidation:")
        print(f"  Avg invalidation time: {smart_results['avg_invalidation_time']:.4f}s")
        print(
            f"  Entries invalidated per change: {smart_results['entries_invalidated_per_change']:.1f}"
        )
        print(f"  Cache misses: {smart_results['cache_misses']}")
        print(f"  Cache hit rate: {smart_results['cache_hit_rate']}")

        # Calculate improvement
        invalidation_speedup = (
            traditional_results["avg_invalidation_time"] / smart_results["avg_invalidation_time"]
        )
        invalidation_reduction = (
            1
            - smart_results["entries_invalidated_per_change"]
            / traditional_results["entries_invalidated_per_change"]
        ) * 100

        print("\nImprovement:")
        print(f"  Invalidation speedup: {invalidation_speedup:.1f}x faster")
        print(f"  Invalidation reduction: {invalidation_reduction:.1f}% fewer invalidations")

        # Assert performance improvements
        # Smart invalidation is more efficient overall even if individual operations have slight overhead
        assert (
            smart_results["entries_invalidated_per_change"]
            < traditional_results["entries_invalidated_per_change"]
        )

        # Check if we meet the target improvements
        assert (
            invalidation_reduction > 80
        ), f"Should reduce invalidations by >80%, got {invalidation_reduction:.1f}%"

        # For very small caches, traditional might be faster per-operation but smart wins on efficiency
        # The real benefit shows with larger caches and real workloads
        if traditional_results["entries_invalidated_per_change"] > 100:
            total_work_traditional = (
                traditional_results["avg_invalidation_time"]
                * traditional_results["entries_invalidated_per_change"]
            )
            total_work_smart = (
                smart_results["avg_invalidation_time"]
                * smart_results["entries_invalidated_per_change"]
            )

            # Use centralized CI tolerance handling
            tolerance_factor = get_ci_tolerance_factor()

            # Smart invalidation should generally be faster, but allow variance on CI
            if is_ci_environment():
                # On CI, the important metric is the 99% reduction in invalidations
                # Allow more timing variance since CI runners are inconsistent
                assert total_work_smart < total_work_traditional * tolerance_factor, (
                    f"Smart invalidation too slow on {get_platform_name()} "
                    f"{'CI' if is_ci_environment() else 'local'}: "
                    f"smart={total_work_smart:.6f} vs traditional={total_work_traditional:.6f} "
                    f"(tolerance factor: {tolerance_factor}x)"
                )
            else:
                # On local development, maintain stricter performance requirements
                assert total_work_smart < total_work_traditional, (
                    f"Smart should do less total work: "
                    f"smart={total_work_smart:.6f} vs traditional={total_work_traditional:.6f}"
                )

    def test_cache_hit_rate(self, large_project):
        """Test that smart invalidation achieves >90% cache hit rate."""
        cache = GranularCache()

        # Build dependencies
        analyzer = ImportAnalyzer(large_project)
        python_files = list(large_project.rglob("*.py"))
        graph = analyzer.build_dependency_graph(python_files)

        for module_name, file_path in graph["modules"].items():
            cache.dependency_tracker.add_file_mapping(Path(file_path), module_name)
            if module_name in graph["imports"]:
                for imported in graph["imports"][module_name]:
                    if imported in graph["modules"]:
                        cache.dependency_tracker.add_import(module_name, imported)

        # Populate cache
        for i, file_path in enumerate(python_files):
            module_name = cache.dependency_tracker.file_to_module.get(file_path)
            for j in range(10):
                cache.set(
                    f"{module_name}:item_{j}",
                    f"value_{i}_{j}",
                    file_path=file_path,
                    module_name=module_name,
                )

        # Simulate normal development workflow
        # - Many reads
        # - Occasional file changes
        # - More reads

        for _ in range(100):  # 100 cache reads
            for file_path in python_files[:10]:  # Read from first 10 files
                module_name = cache.dependency_tracker.file_to_module.get(file_path)
                for j in range(5):
                    cache.get(f"{module_name}:item_{j}")

        # Change one file
        cache.invalidate_file(python_files[0])

        # More reads
        for _ in range(100):
            for file_path in python_files[5:15]:  # Read from different files
                module_name = cache.dependency_tracker.file_to_module.get(file_path)
                for j in range(5):
                    result = cache.get(f"{module_name}:item_{j}")
                    if result is None:
                        # Re-populate on miss
                        cache.set(
                            f"{module_name}:item_{j}",
                            f"new_value_{j}",
                            file_path=file_path,
                            module_name=module_name,
                        )

        # Check metrics
        metrics = cache.get_metrics()
        hit_rate = float(metrics["cache"]["hit_rate"].rstrip("%"))

        print(f"\nCache hit rate: {hit_rate:.1f}%")
        print(f"Total hits: {metrics['cache']['hits']}")
        print(f"Total misses: {metrics['cache']['misses']}")

        # Should achieve >90% hit rate
        assert hit_rate > 90, f"Cache hit rate should be >90%, got {hit_rate:.1f}%"

    def test_memory_efficiency(self, large_project):
        """Test that smart cache uses memory efficiently."""
        import sys

        # Create caches
        traditional_cache = ProjectCache()
        smart_cache = GranularCache()

        # Build dependencies for smart cache
        analyzer = ImportAnalyzer(large_project)
        python_files = list(large_project.rglob("*.py"))
        graph = analyzer.build_dependency_graph(python_files)

        for module_name, file_path in graph["modules"].items():
            smart_cache.dependency_tracker.add_file_mapping(Path(file_path), module_name)
            if module_name in graph["imports"]:
                for imported in graph["imports"][module_name]:
                    if imported in graph["modules"]:
                        smart_cache.dependency_tracker.add_import(module_name, imported)

        # Populate both caches with same data
        for i in range(1000):
            value = f"value_{i}" * 100  # Larger values to see memory difference
            traditional_cache.set(f"key_{i}", value)

            file_path = python_files[i % len(python_files)]
            module_name = smart_cache.dependency_tracker.file_to_module.get(file_path)
            smart_cache.set(f"key_{i}", value, file_path=file_path, module_name=module_name)

        # Measure memory (approximate)
        traditional_size = sys.getsizeof(traditional_cache.cache) + sys.getsizeof(
            traditional_cache.timestamps
        )

        smart_size = (
            sys.getsizeof(smart_cache.cache)
            + sys.getsizeof(smart_cache.timestamps)
            + sys.getsizeof(smart_cache.file_cache)
            + sys.getsizeof(smart_cache.module_cache)
            + sys.getsizeof(smart_cache.dependency_tracker.imports)
            + sys.getsizeof(smart_cache.dependency_tracker.imported_by)
        )

        # Smart cache has overhead but should be reasonable
        overhead_ratio = smart_size / traditional_size

        print("\nMemory usage:")
        print(f"  Traditional cache: {traditional_size} bytes")
        print(f"  Smart cache: {smart_size} bytes")
        print(f"  Overhead ratio: {overhead_ratio:.2f}x")

        # Overhead should be reasonable (less than 2x)
        assert overhead_ratio < 2.0, f"Smart cache overhead too high: {overhead_ratio:.2f}x"

    def test_response_time_target(self, large_project):
        """Test that operations meet <100ms response time target."""
        cache = GranularCache()

        # Build dependencies
        analyzer = ImportAnalyzer(large_project)
        python_files = list(large_project.rglob("*.py"))
        graph = analyzer.build_dependency_graph(python_files)

        for module_name, file_path in graph["modules"].items():
            cache.dependency_tracker.add_file_mapping(Path(file_path), module_name)
            if module_name in graph["imports"]:
                for imported in graph["imports"][module_name]:
                    if imported in graph["modules"]:
                        cache.dependency_tracker.add_import(module_name, imported)

        # Populate cache
        for i in range(1000):
            file_path = python_files[i % len(python_files)]
            module_name = cache.dependency_tracker.file_to_module.get(file_path)
            cache.set(f"key_{i}", f"value_{i}", file_path=file_path, module_name=module_name)

        # Measure operation times
        operation_times = []

        # Test cache gets
        for _ in range(100):
            start = time.perf_counter()
            cache.get(f"key_{_ % 1000}")
            operation_times.append(time.perf_counter() - start)

        # Test cache sets
        for i in range(100):
            file_path = python_files[i % len(python_files)]
            module_name = cache.dependency_tracker.file_to_module.get(file_path)
            start = time.perf_counter()
            cache.set(
                f"new_key_{i}", f"new_value_{i}", file_path=file_path, module_name=module_name
            )
            operation_times.append(time.perf_counter() - start)

        # Test invalidations
        for i in range(10):
            file_path = python_files[i]
            start = time.perf_counter()
            cache.invalidate_file(file_path)
            operation_times.append(time.perf_counter() - start)

        # Calculate percentiles
        operation_times.sort()
        p50 = operation_times[len(operation_times) // 2]
        p95 = operation_times[int(len(operation_times) * 0.95)]
        p99 = operation_times[int(len(operation_times) * 0.99)]

        print("\nOperation response times:")
        print(f"  P50: {p50 * 1000:.2f}ms")
        print(f"  P95: {p95 * 1000:.2f}ms")
        print(f"  P99: {p99 * 1000:.2f}ms")

        # P95 should be <100ms
        assert p95 < 0.1, f"P95 response time should be <100ms, got {p95 * 1000:.2f}ms"
