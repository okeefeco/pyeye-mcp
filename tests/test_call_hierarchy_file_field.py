"""Test that callee dicts in get_call_hierarchy include a 'file' field.

This test addresses issue #316 (tool ergonomics improvements): callee dicts
should include a 'file' field for consistency with caller dicts.
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer


class TestCallHierarchyCalleeFileField:
    """Tests for the 'file' field in callee dicts returned by get_call_hierarchy."""

    @pytest.mark.asyncio
    async def test_callee_dicts_include_file_field(self):
        """Each callee dict should include a 'file' key with a string (POSIX) value.

        The test mocks Jedi internals to ensure the callee-building code path
        is exercised, then asserts the 'file' field is present.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            module_file = Path(temp_dir) / "sample.py"
            module_file_posix = module_file.as_posix()
            module_file.write_text("""\
def inner():
    return 42


def outer():
    return inner()
""")

            # Mock a Jedi Name that represents a function definition (the symbol we search for)
            mock_function_def = MagicMock()
            mock_function_def.type = "function"
            mock_function_def.module_path = module_file
            mock_function_def.line = 5
            mock_function_def.column = 0

            # Mock a Jedi Name that represents a callee (non-definition function usage)
            mock_callee_name = MagicMock()
            mock_callee_name.type = "function"
            mock_callee_name.name = "inner"
            mock_callee_name.line = 6  # Within range of outer (line 5 + 50)
            mock_callee_name.column = 11
            mock_callee_name.module_path = module_file
            mock_callee_name.is_definition.return_value = False

            # Mock a jedi.Script
            mock_script = MagicMock()
            mock_script.get_references.return_value = []
            mock_script.get_names.return_value = [mock_callee_name]

            analyzer = JediAnalyzer(temp_dir)

            with (
                patch.object(
                    analyzer,
                    "_search_all_scopes",
                    new=AsyncMock(return_value=[mock_function_def]),
                ),
                patch(
                    "pyeye.analyzers.jedi_analyzer.read_file_async",
                    new=AsyncMock(return_value=module_file.read_text()),
                ),
                patch("pyeye.analyzers.jedi_analyzer.jedi.Script", return_value=mock_script),
            ):
                result = await analyzer.get_call_hierarchy(
                    function_name="outer",
                    file=module_file_posix,
                )

            assert "callees" in result, f"Expected 'callees' key in result: {result}"
            callees = result["callees"]
            assert isinstance(callees, list), f"Expected callees to be a list: {callees}"
            assert (
                len(callees) > 0
            ), "Expected at least one callee to be returned by the mocked jedi"

            for callee in callees:
                assert "file" in callee, (
                    f"Callee dict missing 'file' key: {callee}\n"
                    "This is issue #316: callee dicts should include a 'file' field "
                    "for consistency with caller dicts."
                )
                # file should be a string (POSIX path) or None (for builtins)
                assert callee["file"] is None or isinstance(
                    callee["file"], str
                ), f"Callee 'file' should be str or None, got {type(callee['file'])}: {callee}"
                # If file is a string, it should use forward slashes (POSIX)
                if callee["file"] is not None:
                    assert (
                        "\\" not in callee["file"]
                    ), f"Callee 'file' should be POSIX path (no backslashes): {callee['file']}"
                    assert callee["file"].endswith(
                        "sample.py"
                    ), f"Expected callee 'file' to point to sample.py: {callee['file']}"

    @pytest.mark.asyncio
    async def test_callee_file_field_is_posix_string_not_path_object(self):
        """Callee 'file' field must be a POSIX path string, not a Path object.

        Ensures the value is JSON-serializable (Path objects are not).
        """
        import json

        with tempfile.TemporaryDirectory() as temp_dir:
            module_file = Path(temp_dir) / "sample.py"
            module_file_posix = module_file.as_posix()
            module_file.write_text("""\
def inner():
    return 42


def outer():
    return inner()
""")

            mock_function_def = MagicMock()
            mock_function_def.type = "function"
            mock_function_def.module_path = module_file
            mock_function_def.line = 5
            mock_function_def.column = 0

            mock_callee_name = MagicMock()
            mock_callee_name.type = "function"
            mock_callee_name.name = "inner"
            mock_callee_name.line = 6
            mock_callee_name.column = 11
            mock_callee_name.module_path = module_file
            mock_callee_name.is_definition.return_value = False

            mock_script = MagicMock()
            mock_script.get_references.return_value = []
            mock_script.get_names.return_value = [mock_callee_name]

            analyzer = JediAnalyzer(temp_dir)

            with (
                patch.object(
                    analyzer,
                    "_search_all_scopes",
                    new=AsyncMock(return_value=[mock_function_def]),
                ),
                patch(
                    "pyeye.analyzers.jedi_analyzer.read_file_async",
                    new=AsyncMock(return_value=module_file.read_text()),
                ),
                patch("pyeye.analyzers.jedi_analyzer.jedi.Script", return_value=mock_script),
            ):
                result = await analyzer.get_call_hierarchy(
                    function_name="outer",
                    file=module_file_posix,
                )

            callees = result.get("callees", [])
            assert len(callees) > 0, "Expected at least one callee from mocked jedi"

            for callee in callees:
                assert "file" in callee, f"Callee dict missing 'file' key: {callee}"

                # Must be JSON serializable (Path objects raise TypeError with json.dumps)
                try:
                    json.dumps(callee)
                except TypeError as exc:
                    pytest.fail(f"Callee dict is not JSON-serializable: {callee}\nError: {exc}")

                file_val = callee["file"]
                assert not isinstance(
                    file_val, Path
                ), f"Callee 'file' must not be a Path object, got: {type(file_val)}"

    @pytest.mark.asyncio
    async def test_callee_file_field_is_none_for_builtin(self):
        """Callee 'file' should be None when module_path is falsy (e.g. builtins)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            module_file = Path(temp_dir) / "sample.py"
            module_file.write_text("def outer(): pass\n")

            mock_function_def = MagicMock()
            mock_function_def.type = "function"
            mock_function_def.module_path = module_file
            mock_function_def.line = 1
            mock_function_def.column = 0

            # Simulate a builtin/C-extension callee with no module_path
            mock_callee_name = MagicMock()
            mock_callee_name.type = "function"
            mock_callee_name.name = "len"
            mock_callee_name.line = 1
            mock_callee_name.column = 14
            mock_callee_name.module_path = None  # builtins have no module_path
            mock_callee_name.is_definition.return_value = False

            mock_script = MagicMock()
            mock_script.get_references.return_value = []
            mock_script.get_names.return_value = [mock_callee_name]

            analyzer = JediAnalyzer(temp_dir)

            with (
                patch.object(
                    analyzer,
                    "_search_all_scopes",
                    new=AsyncMock(return_value=[mock_function_def]),
                ),
                patch(
                    "pyeye.analyzers.jedi_analyzer.read_file_async",
                    new=AsyncMock(return_value=module_file.read_text()),
                ),
                patch("pyeye.analyzers.jedi_analyzer.jedi.Script", return_value=mock_script),
            ):
                result = await analyzer.get_call_hierarchy(
                    function_name="outer",
                    file=module_file.as_posix(),
                )

            callees = result.get("callees", [])
            assert len(callees) > 0, "Expected at least one callee from mocked jedi"

            builtin_callee = callees[0]
            assert (
                "file" in builtin_callee
            ), f"Callee dict missing 'file' key even for builtins: {builtin_callee}"
            assert (
                builtin_callee["file"] is None
            ), f"Expected callee['file'] to be None for builtins, got: {builtin_callee['file']}"
