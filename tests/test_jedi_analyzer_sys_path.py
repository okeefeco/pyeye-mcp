"""Tests for the ``JediAnalyzer.added_sys_path`` stored attribute (#423).

``added_sys_path`` used to be a local variable in ``JediAnalyzer.__init__``
that was passed to ``jedi.Project(added_sys_path=...)`` and then discarded.
A future containment enumerator needs a single, ordered, list-derived path
source whose determinism underpins roots ordering (and therefore namespace
collision-winner determinism). These tests pin the public attribute to a
stable ``list[Path]`` that equals the same paths handed to ``jedi.Project``.
"""

from pathlib import Path

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.config import ProjectConfig

_FIXTURE = Path(__file__).parent / "fixtures" / "added_sys_path_project"


class TestAddedSysPathAttribute:
    """Pin ``JediAnalyzer.added_sys_path`` as a stored ``list[Path]``."""

    def test_added_sys_path_is_list_of_path_containing_src_root(self) -> None:
        """For a src-layout project the attribute is a ``list[Path]`` with src."""
        config = ProjectConfig(str(_FIXTURE))
        analyzer = JediAnalyzer(str(_FIXTURE), config=config)

        assert isinstance(analyzer.added_sys_path, list)
        assert all(isinstance(p, Path) for p in analyzer.added_sys_path)

        src_root = (_FIXTURE / "src").resolve().as_posix()
        attr_posix = [p.resolve().as_posix() for p in analyzer.added_sys_path]
        assert (
            src_root in attr_posix
        ), f"Expected src root {src_root} in added_sys_path, got {attr_posix}"

    def test_added_sys_path_is_a_plain_list_with_stable_order(self) -> None:
        """The attribute is an ordered ``list`` (not a ``set``) and is stable."""
        first = JediAnalyzer(str(_FIXTURE), config=ProjectConfig(str(_FIXTURE)))
        second = JediAnalyzer(str(_FIXTURE), config=ProjectConfig(str(_FIXTURE)))

        assert type(first.added_sys_path) is list
        # Same project, two constructions -> identical order, run to run.
        first_posix = [p.resolve().as_posix() for p in first.added_sys_path]
        second_posix = [p.resolve().as_posix() for p in second.added_sys_path]
        assert first_posix == second_posix

    def test_added_sys_path_matches_what_is_passed_to_jedi(self) -> None:
        """The stored attribute equals the list handed to ``jedi.Project``.

        No second computation path: the attribute is the same set of paths,
        in the same order, just typed as ``Path`` instead of posix ``str``.
        """
        from unittest.mock import Mock, patch

        config = ProjectConfig(str(_FIXTURE))
        with patch("pyeye.analyzers.jedi_analyzer.jedi.Project") as mock_project:
            mock_project.return_value = Mock()
            analyzer = JediAnalyzer(str(_FIXTURE), config=config)

        passed = mock_project.call_args.kwargs["added_sys_path"]
        attr_posix = [p.as_posix() for p in analyzer.added_sys_path]
        assert attr_posix == list(passed)

    def test_added_sys_path_empty_without_config(self) -> None:
        """Without config (no src/namespace roots) the attribute is empty."""
        analyzer = JediAnalyzer(str(_FIXTURE), config=None)
        assert analyzer.added_sys_path == []
