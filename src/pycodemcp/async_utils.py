"""Async file operations utilities for non-blocking I/O."""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiofiles  # type: ignore[import-untyped]


async def read_file_async(path: Path) -> str:
    """Read file contents asynchronously.

    Args:
        path: Path to the file to read

    Returns:
        File contents as string

    Raises:
        FileNotFoundError: If file doesn't exist
        IOError: If file cannot be read
    """
    async with aiofiles.open(path, encoding="utf-8") as f:
        content: str = await f.read()
        return content


async def write_file_async(path: Path, content: str) -> None:
    """Write content to file asynchronously.

    Args:
        path: Path to the file to write
        content: Content to write

    Raises:
        IOError: If file cannot be written
    """
    async with aiofiles.open(path, mode="w", encoding="utf-8") as f:
        await f.write(content)


async def read_file_safe(path: Path, default: str | None = None) -> str | None:
    """Read file asynchronously with error handling.

    Args:
        path: Path to the file to read
        default: Default value if file cannot be read

    Returns:
        File contents or default value
    """
    try:
        return await read_file_async(path)
    except OSError:
        return default


async def file_exists_async(path: Path) -> bool:
    """Check if file exists asynchronously.

    Args:
        path: Path to check

    Returns:
        True if file exists, False otherwise
    """
    return await asyncio.to_thread(path.exists)


async def glob_async(pattern: str, path: Path) -> list[Path]:
    """Glob files asynchronously.

    Args:
        pattern: Glob pattern
        path: Base path to search in

    Returns:
        List of matching paths
    """
    return await asyncio.to_thread(lambda: list(path.glob(pattern)))


async def rglob_async(pattern: str, path: Path) -> list[Path]:
    """Recursively glob files asynchronously.

    Args:
        pattern: Glob pattern
        path: Base path to search in

    Returns:
        List of matching paths
    """
    return await asyncio.to_thread(lambda: list(path.rglob(pattern)))


async def read_files_batch(paths: list[Path]) -> dict[Path, str | None]:
    """Read multiple files concurrently.

    Args:
        paths: List of file paths to read

    Returns:
        Dictionary mapping paths to their contents (None if error)
    """
    tasks = [read_file_safe(path) for path in paths]
    results = await asyncio.gather(*tasks)
    return dict(zip(paths, results, strict=False))


async def process_files_concurrent(
    paths: list[Path], processor: Callable[[Path], Any], max_concurrent: int = 10
) -> list[Any]:
    """Process multiple files concurrently with a limit.

    Args:
        paths: List of file paths to process
        processor: Async function to process each file
        max_concurrent: Maximum concurrent operations

    Returns:
        List of processed results
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_with_limit(path: Path) -> Any:
        async with semaphore:
            return await processor(path)

    tasks = [process_with_limit(path) for path in paths]
    return await asyncio.gather(*tasks, return_exceptions=True)
