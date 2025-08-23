"""Async file operations utilities for non-blocking I/O."""

import asyncio
import logging
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiofiles  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


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


async def ripgrep_async(
    pattern: str, paths: list[Path], include_pattern: str | None = None, case_sensitive: bool = True
) -> list[Path]:
    """Use ripgrep to find files containing a pattern.

    Falls back to Python-based search if ripgrep is not available.

    Args:
        pattern: Pattern to search for (regex or literal string)
        paths: List of paths to search in
        include_pattern: File pattern to include (e.g., "*.py")
        case_sensitive: Whether search should be case-sensitive

    Returns:
        List of file paths containing the pattern
    """
    # Check if ripgrep is available
    if not shutil.which("rg"):
        logger.debug("ripgrep not found, falling back to Python-based search")
        return await _python_grep_fallback(pattern, paths, include_pattern, case_sensitive)

    try:
        # Build ripgrep command
        cmd = ["rg", "--files-with-matches", "--no-heading", "--no-line-number"]

        if not case_sensitive:
            cmd.append("-i")

        if include_pattern:
            cmd.extend(["--glob", include_pattern])

        # Add the pattern
        cmd.append(pattern)

        # Add paths
        cmd.extend(str(p) for p in paths)

        # Run ripgrep
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        stdout, _ = await process.communicate()

        if process.returncode not in (0, 1):  # 0 = found matches, 1 = no matches
            logger.warning(f"ripgrep failed with code {process.returncode}, falling back")
            return await _python_grep_fallback(pattern, paths, include_pattern, case_sensitive)

        # Parse output
        if not stdout:
            return []

        files = stdout.decode("utf-8").strip().split("\n")
        return [Path(f) for f in files if f]

    except Exception as e:
        logger.warning(f"Error running ripgrep: {e}, falling back to Python search")
        return await _python_grep_fallback(pattern, paths, include_pattern, case_sensitive)


async def _python_grep_fallback(
    pattern: str, paths: list[Path], include_pattern: str | None = None, case_sensitive: bool = True
) -> list[Path]:
    """Python-based grep fallback when ripgrep is not available.

    Args:
        pattern: Pattern to search for
        paths: List of paths to search in
        include_pattern: File pattern to include
        case_sensitive: Whether search should be case-sensitive

    Returns:
        List of file paths containing the pattern
    """
    import re

    # Compile regex pattern
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = re.compile(pattern, flags)
    except re.error:
        # If pattern is not valid regex, treat as literal string
        regex = re.compile(re.escape(pattern), flags)

    matching_files = []

    for base_path in paths:
        if base_path.is_file():
            # Single file
            files_to_check = [base_path]
        else:
            # Directory - find all matching files
            if include_pattern:
                files_to_check = list(base_path.rglob(include_pattern))
            else:
                files_to_check = list(base_path.rglob("*"))

        # Check each file
        for file_path in files_to_check:
            if not file_path.is_file():
                continue

            try:
                content = await read_file_safe(file_path)
                if content and regex.search(content):
                    matching_files.append(file_path)
            except Exception:
                # Skip files that can't be read
                continue

    return matching_files
