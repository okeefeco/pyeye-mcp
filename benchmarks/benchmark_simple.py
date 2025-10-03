"""Simplified performance benchmark for Python Code Intelligence MCP Server."""

import asyncio
import shutil
import tempfile
import time
from pathlib import Path

from pyeye.analyzers.jedi_analyzer import JediAnalyzer


def create_test_project(size: str = "small") -> str:
    """Create a test project with Python files."""
    temp_dir = tempfile.mkdtemp(prefix="bench_")

    file_counts = {"small": 10, "medium": 100, "large": 1000}
    count = file_counts.get(size, 10)

    # Create simple Python files
    for i in range(count):
        pkg_dir = Path(temp_dir) / f"pkg_{i % 5}"
        pkg_dir.mkdir(exist_ok=True)

        module_file = pkg_dir / f"module_{i}.py"
        module_file.write_text(
            f'''
"""Module {i} for benchmarking."""

def function_{i}(x: int) -> int:
    """Test function."""
    return x * 2

class Class_{i}:
    """Test class."""

    def method(self, value: str) -> str:
        """Test method."""
        return value.upper()
'''
        )

    return temp_dir


async def benchmark_symbol_search(project_path: str, iterations: int = 10) -> dict[str, float]:
    """Benchmark symbol search performance."""
    analyzer = JediAnalyzer(project_path)

    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        await analyzer.find_symbol("function_0")
        duration = time.perf_counter() - start
        times.append(duration * 1000)  # Convert to ms

    times.sort()
    return {
        "min_ms": times[0],
        "median_ms": times[len(times) // 2],
        "max_ms": times[-1],
    }


async def main() -> None:
    """Run simple benchmark."""
    print("Creating test project...")
    project_path = create_test_project("medium")

    try:
        print("Running benchmark...")
        results = await benchmark_symbol_search(project_path)

        print("\nResults:")
        print(f"  Min: {results['min_ms']:.2f}ms")
        print(f"  Median: {results['median_ms']:.2f}ms")
        print(f"  Max: {results['max_ms']:.2f}ms")

    finally:
        shutil.rmtree(project_path)
        print(f"\nCleaned up {project_path}")


if __name__ == "__main__":
    asyncio.run(main())
