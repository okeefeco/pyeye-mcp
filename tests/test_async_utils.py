"""Comprehensive tests for async_utils module."""

import asyncio
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from pycodemcp.async_utils import (
    file_exists_async,
    glob_async,
    process_files_concurrent,
    read_file_async,
    read_file_safe,
    read_files_batch,
    rglob_async,
    write_file_async,
)


@pytest.mark.asyncio
class TestReadFileAsync:
    """Test read_file_async function."""

    async def test_read_file_basic(self, tmp_path):
        """Test reading a basic file."""
        test_file = tmp_path / "test.txt"
        test_content = "Hello, World!"
        test_file.write_text(test_content)

        content = await read_file_async(test_file)
        assert content == test_content

    async def test_read_file_unicode(self, tmp_path):
        """Test reading a file with Unicode content."""
        test_file = tmp_path / "unicode.txt"
        test_content = "Hello, 世界! 🌍"
        test_file.write_text(test_content, encoding="utf-8")

        content = await read_file_async(test_file)
        assert content == test_content

    async def test_read_file_multiline(self, tmp_path):
        """Test reading a multiline file."""
        test_file = tmp_path / "multiline.txt"
        test_content = "Line 1\nLine 2\nLine 3"
        test_file.write_text(test_content)

        content = await read_file_async(test_file)
        assert content == test_content

    async def test_read_file_not_found(self):
        """Test reading a non-existent file."""
        non_existent = Path("/tmp/does_not_exist_12345.txt")

        with pytest.raises(FileNotFoundError):
            await read_file_async(non_existent)

    @pytest.mark.skipif(os.name == "nt", reason="Windows handles permissions differently")
    async def test_read_file_permission_error(self, tmp_path):
        """Test reading a file without permissions."""
        test_file = tmp_path / "no_read.txt"
        test_file.write_text("secret")
        test_file.chmod(0o000)

        try:
            with pytest.raises(OSError):
                await read_file_async(test_file)
        finally:
            # Restore permissions for cleanup
            test_file.chmod(0o644)

    async def test_read_file_empty(self, tmp_path):
        """Test reading an empty file."""
        test_file = tmp_path / "empty.txt"
        test_file.write_text("")

        content = await read_file_async(test_file)
        assert content == ""

    async def test_read_file_large(self, tmp_path):
        """Test reading a large file."""
        test_file = tmp_path / "large.txt"
        test_content = "x" * 100000  # 100KB of data
        test_file.write_text(test_content)

        content = await read_file_async(test_file)
        assert content == test_content
        assert len(content) == 100000


@pytest.mark.asyncio
class TestWriteFileAsync:
    """Test write_file_async function."""

    async def test_write_file_basic(self, tmp_path):
        """Test writing a basic file."""
        test_file = tmp_path / "output.txt"
        test_content = "Hello, World!"

        await write_file_async(test_file, test_content)

        assert test_file.exists()
        assert test_file.read_text() == test_content

    async def test_write_file_overwrite(self, tmp_path):
        """Test overwriting an existing file."""
        test_file = tmp_path / "overwrite.txt"
        test_file.write_text("Old content")

        new_content = "New content"
        await write_file_async(test_file, new_content)

        assert test_file.read_text() == new_content

    async def test_write_file_unicode(self, tmp_path):
        """Test writing Unicode content."""
        test_file = tmp_path / "unicode_out.txt"
        test_content = "Unicode: 日本語 🎌"

        await write_file_async(test_file, test_content)

        assert test_file.read_text(encoding="utf-8") == test_content

    async def test_write_file_multiline(self, tmp_path):
        """Test writing multiline content."""
        test_file = tmp_path / "multiline_out.txt"
        test_content = "Line 1\nLine 2\nLine 3"

        await write_file_async(test_file, test_content)

        assert test_file.read_text() == test_content

    async def test_write_file_empty(self, tmp_path):
        """Test writing empty content."""
        test_file = tmp_path / "empty_out.txt"

        await write_file_async(test_file, "")

        assert test_file.exists()
        assert test_file.read_text() == ""

    @pytest.mark.skipif(os.name == "nt", reason="Windows handles permissions differently")
    async def test_write_file_permission_error(self, tmp_path):
        """Test writing to a directory without permissions."""
        protected_dir = tmp_path / "protected"
        protected_dir.mkdir()
        protected_dir.chmod(0o555)  # Read-only directory

        test_file = protected_dir / "file.txt"

        try:
            with pytest.raises(OSError):
                await write_file_async(test_file, "content")
        finally:
            # Restore permissions for cleanup
            protected_dir.chmod(0o755)

    async def test_write_file_create_in_subdir(self, tmp_path):
        """Test writing file in a subdirectory."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        test_file = subdir / "file.txt"

        await write_file_async(test_file, "content in subdir")

        assert test_file.exists()
        assert test_file.read_text() == "content in subdir"


@pytest.mark.asyncio
class TestReadFileSafe:
    """Test read_file_safe function."""

    async def test_read_file_safe_success(self, tmp_path):
        """Test safe reading of an existing file."""
        test_file = tmp_path / "safe.txt"
        test_content = "Safe content"
        test_file.write_text(test_content)

        content = await read_file_safe(test_file)
        assert content == test_content

    async def test_read_file_safe_not_found_default_none(self):
        """Test safe reading with default None for missing file."""
        non_existent = Path("/tmp/does_not_exist_safe.txt")

        content = await read_file_safe(non_existent)
        assert content is None

    async def test_read_file_safe_not_found_custom_default(self):
        """Test safe reading with custom default for missing file."""
        non_existent = Path("/tmp/does_not_exist_safe2.txt")

        content = await read_file_safe(non_existent, default="fallback")
        assert content == "fallback"

    @pytest.mark.skipif(os.name == "nt", reason="Windows handles permissions differently")
    async def test_read_file_safe_permission_error(self, tmp_path):
        """Test safe reading of file without permissions."""
        test_file = tmp_path / "no_read_safe.txt"
        test_file.write_text("secret")
        test_file.chmod(0o000)

        try:
            content = await read_file_safe(test_file, default="denied")
            assert content == "denied"
        finally:
            # Restore permissions for cleanup
            test_file.chmod(0o644)

    async def test_read_file_safe_empty_file(self, tmp_path):
        """Test safe reading of empty file."""
        test_file = tmp_path / "empty_safe.txt"
        test_file.write_text("")

        content = await read_file_safe(test_file, default="empty_default")
        assert content == ""  # Should return actual empty content, not default

    async def test_read_file_safe_with_oserror(self, tmp_path):
        """Test handling of OSError in read_file_safe."""
        test_file = tmp_path / "test.txt"

        with patch("pycodemcp.async_utils.read_file_async") as mock_read:
            mock_read.side_effect = OSError("Disk error")

            content = await read_file_safe(test_file, default="error_fallback")
            assert content == "error_fallback"


@pytest.mark.asyncio
class TestFileExistsAsync:
    """Test file_exists_async function."""

    async def test_file_exists_true(self, tmp_path):
        """Test checking an existing file."""
        test_file = tmp_path / "exists.txt"
        test_file.write_text("content")

        exists = await file_exists_async(test_file)
        assert exists is True

    async def test_file_exists_false(self):
        """Test checking a non-existent file."""
        non_existent = Path("/tmp/does_not_exist_check.txt")

        exists = await file_exists_async(non_existent)
        assert exists is False

    async def test_file_exists_directory(self, tmp_path):
        """Test checking if a directory exists."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        exists = await file_exists_async(test_dir)
        assert exists is True

    async def test_file_exists_symlink(self, tmp_path):
        """Test checking a symlink."""
        real_file = tmp_path / "real.txt"
        real_file.write_text("content")
        symlink = tmp_path / "link.txt"
        symlink.symlink_to(real_file)

        exists = await file_exists_async(symlink)
        assert exists is True

    async def test_file_exists_broken_symlink(self, tmp_path):
        """Test checking a broken symlink."""
        symlink = tmp_path / "broken_link.txt"
        symlink.symlink_to("/tmp/nonexistent_target.txt")

        exists = await file_exists_async(symlink)
        assert exists is False


@pytest.mark.asyncio
class TestGlobAsync:
    """Test glob_async function."""

    async def test_glob_basic(self, tmp_path):
        """Test basic glob pattern."""
        # Create test files
        (tmp_path / "test1.py").write_text("")
        (tmp_path / "test2.py").write_text("")
        (tmp_path / "other.txt").write_text("")

        results = await glob_async("*.py", tmp_path)

        assert len(results) == 2
        assert all(p.suffix == ".py" for p in results)

    async def test_glob_no_matches(self, tmp_path):
        """Test glob with no matches."""
        results = await glob_async("*.xyz", tmp_path)
        assert results == []

    async def test_glob_all_files(self, tmp_path):
        """Test glob matching all files."""
        # Create test files
        (tmp_path / "file1.txt").write_text("")
        (tmp_path / "file2.py").write_text("")

        results = await glob_async("*", tmp_path)

        assert len(results) == 2

    async def test_glob_subdirectory(self, tmp_path):
        """Test glob in subdirectory."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "test.py").write_text("")

        results = await glob_async("subdir/*.py", tmp_path)

        assert len(results) == 1
        assert results[0].name == "test.py"

    async def test_glob_complex_pattern(self, tmp_path):
        """Test complex glob pattern."""
        (tmp_path / "test_1.py").write_text("")
        (tmp_path / "test_2.py").write_text("")
        (tmp_path / "test_abc.py").write_text("")

        results = await glob_async("test_[0-9].py", tmp_path)

        assert len(results) == 2
        assert all("test_" in p.name for p in results)


@pytest.mark.asyncio
class TestRglobAsync:
    """Test rglob_async function."""

    async def test_rglob_recursive(self, tmp_path):
        """Test recursive glob pattern."""
        # Create nested structure
        (tmp_path / "test1.py").write_text("")
        subdir1 = tmp_path / "subdir1"
        subdir1.mkdir()
        (subdir1 / "test2.py").write_text("")
        subdir2 = subdir1 / "subdir2"
        subdir2.mkdir()
        (subdir2 / "test3.py").write_text("")

        results = await rglob_async("*.py", tmp_path)

        assert len(results) == 3
        assert all(p.suffix == ".py" for p in results)

    async def test_rglob_no_matches(self, tmp_path):
        """Test recursive glob with no matches."""
        results = await rglob_async("*.xyz", tmp_path)
        assert results == []

    async def test_rglob_directory_pattern(self, tmp_path):
        """Test recursive glob matching directories."""
        # Create nested test directories
        (tmp_path / "test_dir").mkdir()
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "test_dir").mkdir()

        results = await rglob_async("test_*", tmp_path)

        assert len(results) == 2

    async def test_rglob_all_files(self, tmp_path):
        """Test recursive glob for all files."""
        # Create nested files
        (tmp_path / "file1.txt").write_text("")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file2.txt").write_text("")

        results = await rglob_async("*.txt", tmp_path)

        assert len(results) == 2


@pytest.mark.asyncio
class TestReadFilesBatch:
    """Test read_files_batch function."""

    async def test_read_files_batch_success(self, tmp_path):
        """Test batch reading of multiple files."""
        # Create test files
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file3 = tmp_path / "file3.txt"

        file1.write_text("Content 1")
        file2.write_text("Content 2")
        file3.write_text("Content 3")

        paths = [file1, file2, file3]
        results = await read_files_batch(paths)

        assert len(results) == 3
        assert results[file1] == "Content 1"
        assert results[file2] == "Content 2"
        assert results[file3] == "Content 3"

    async def test_read_files_batch_mixed(self, tmp_path):
        """Test batch reading with some failures."""
        # Create only some files
        file1 = tmp_path / "exists.txt"
        file2 = tmp_path / "missing.txt"
        file3 = tmp_path / "also_exists.txt"

        file1.write_text("Exists")
        file3.write_text("Also exists")

        paths = [file1, file2, file3]
        results = await read_files_batch(paths)

        assert results[file1] == "Exists"
        assert results[file2] is None  # Missing file returns None
        assert results[file3] == "Also exists"

    async def test_read_files_batch_empty_list(self):
        """Test batch reading with empty list."""
        results = await read_files_batch([])
        assert results == {}

    async def test_read_files_batch_single_file(self, tmp_path):
        """Test batch reading with single file."""
        file1 = tmp_path / "single.txt"
        file1.write_text("Single content")

        results = await read_files_batch([file1])

        assert len(results) == 1
        assert results[file1] == "Single content"

    async def test_read_files_batch_concurrent(self, tmp_path):
        """Test that files are read concurrently."""
        # Create multiple files
        files = []
        for i in range(10):
            file = tmp_path / f"file{i}.txt"
            file.write_text(f"Content {i}")
            files.append(file)

        # This should be fast due to concurrent reading
        results = await read_files_batch(files)

        assert len(results) == 10
        for i, file in enumerate(files):
            assert results[file] == f"Content {i}"


@pytest.mark.asyncio
class TestProcessFilesConcurrent:
    """Test process_files_concurrent function."""

    async def test_process_files_basic(self, tmp_path):
        """Test basic concurrent file processing."""
        # Create test files
        files = []
        for i in range(5):
            file = tmp_path / f"file{i}.txt"
            file.write_text(f"Content {i}")
            files.append(file)

        # Simple processor that reads and returns length
        async def processor(path: Path) -> int:
            content = await read_file_async(path)
            return len(content)

        results = await process_files_concurrent(files, processor)

        assert len(results) == 5
        assert all(isinstance(r, int) for r in results)

    async def test_process_files_with_limit(self, tmp_path):
        """Test concurrent processing with concurrency limit."""
        # Create test files
        files = []
        for i in range(10):
            file = tmp_path / f"file{i}.txt"
            file.write_text(f"Content {i}")
            files.append(file)

        call_count = 0
        max_concurrent = 0
        current_concurrent = 0

        async def processor(path: Path) -> str:
            nonlocal call_count, max_concurrent, current_concurrent
            current_concurrent += 1
            max_concurrent = max(max_concurrent, current_concurrent)
            call_count += 1

            # Simulate some async work
            await asyncio.sleep(0.01)

            current_concurrent -= 1
            return path.name

        results = await process_files_concurrent(files, processor, max_concurrent=3)

        assert len(results) == 10
        assert call_count == 10
        assert max_concurrent <= 3  # Should respect concurrency limit

    async def test_process_files_with_errors(self, tmp_path):
        """Test concurrent processing with some errors."""
        # Create test files
        files = []
        for i in range(5):
            file = tmp_path / f"file{i}.txt"
            file.write_text(f"Content {i}")
            files.append(file)

        async def processor(path: Path) -> str:
            if "file2" in path.name:
                raise ValueError("Error processing file2")
            return path.name

        results = await process_files_concurrent(files, processor)

        assert len(results) == 5
        # Check that error is captured as exception
        assert isinstance(results[2], ValueError)
        # Other results should be strings
        assert isinstance(results[0], str)
        assert isinstance(results[1], str)

    async def test_process_files_empty_list(self):
        """Test processing empty list of files."""

        async def processor(path: Path) -> str:
            return path.name

        results = await process_files_concurrent([], processor)

        assert results == []

    async def test_process_files_single_file(self, tmp_path):
        """Test processing single file."""
        file = tmp_path / "single.txt"
        file.write_text("Single")

        async def processor(path: Path) -> str:
            content = await read_file_async(path)
            return content.upper()

        results = await process_files_concurrent([file], processor)

        assert len(results) == 1
        assert results[0] == "SINGLE"

    async def test_process_files_large_batch(self, tmp_path):
        """Test processing large batch of files."""
        # Create many files
        files = []
        for i in range(50):
            file = tmp_path / f"file{i}.txt"
            file.write_text(f"{i}")
            files.append(file)

        async def processor(path: Path) -> int:
            content = await read_file_async(path)
            return int(content)

        results = await process_files_concurrent(files, processor, max_concurrent=10)

        assert len(results) == 50
        assert sum(results) == sum(range(50))  # 0 + 1 + 2 + ... + 49

    async def test_process_files_async_processor(self, tmp_path):
        """Test with async processor function."""
        files = []
        for i in range(3):
            file = tmp_path / f"file{i}.txt"
            file.write_text(f"Data {i}")
            files.append(file)

        async def async_processor(path: Path) -> tuple[str, int]:
            # Simulate complex async processing
            content = await read_file_async(path)
            await asyncio.sleep(0.01)  # Simulate async work
            return (path.name, len(content))

        results = await process_files_concurrent(files, async_processor, max_concurrent=2)

        assert len(results) == 3
        assert all(isinstance(r, tuple) for r in results)
        assert all(len(r) == 2 for r in results)


@pytest.mark.asyncio
class TestIntegration:
    """Integration tests combining multiple functions."""

    async def test_read_write_cycle(self, tmp_path):
        """Test complete read-write cycle."""
        test_file = tmp_path / "cycle.txt"
        original_content = "Original content"

        # Write
        await write_file_async(test_file, original_content)

        # Read back
        read_content = await read_file_async(test_file)
        assert read_content == original_content

        # Modify and write again
        modified_content = "Modified content"
        await write_file_async(test_file, modified_content)

        # Read again
        final_content = await read_file_async(test_file)
        assert final_content == modified_content

    async def test_glob_and_batch_read(self, tmp_path):
        """Test globbing files and batch reading them."""
        # Create Python files
        for i in range(5):
            file = tmp_path / f"module{i}.py"
            file.write_text(f"# Module {i}")

        # Glob Python files
        py_files = await glob_async("*.py", tmp_path)
        assert len(py_files) == 5

        # Batch read them
        contents = await read_files_batch(py_files)
        assert len(contents) == 5
        assert all(content and content.startswith("#") for content in contents.values())

    async def test_recursive_processing(self, tmp_path):
        """Test recursive file discovery and processing."""
        # Create nested structure
        for i in range(3):
            subdir = tmp_path / f"dir{i}"
            subdir.mkdir()
            for j in range(2):
                file = subdir / f"file{j}.txt"
                file.write_text(f"Dir {i} File {j}")

        # Recursively find all txt files
        all_files = await rglob_async("*.txt", tmp_path)
        assert len(all_files) == 6

        # Process them concurrently
        async def count_words(path: Path) -> int:
            content = await read_file_async(path)
            return len(content.split())

        word_counts = await process_files_concurrent(all_files, count_words, max_concurrent=4)

        assert len(word_counts) == 6
        assert all(count == 4 for count in word_counts)  # Each file has 4 words
