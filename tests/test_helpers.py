"""Shared test helper functions."""

from pathlib import Path


def assert_path_in_list(path: str | Path, path_list: list[str | Path]) -> None:
    """Assert that a path is in a list of paths, handling Path objects correctly."""
    path = Path(path).resolve()
    resolved_list = [Path(p).resolve() for p in path_list]
    assert path in resolved_list, f"{path} not found in {resolved_list}"


def assert_path_equal(path1: str | Path, path2: str | Path) -> None:
    """Assert that two paths are equal, handling Path objects correctly."""
    assert Path(path1).resolve() == Path(path2).resolve()
