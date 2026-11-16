"""Containment, keys and project matching go through path_utils (#717).

The sites in ``validation``, ``config``, ``typeref``, ``resolver``,
``mcp/operations/resolve`` and ``configure_packages`` used to call
``.resolve()`` / ``.relative_to()`` themselves. These pin the behaviour they
now get from ``normalize_path`` / ``path_to_key`` / ``relative_within``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pyeye.config import ProjectConfig
from pyeye.exceptions import ValidationError
from pyeye.mcp.operations import typeref
from pyeye.path_utils import path_to_key
from pyeye.validation import PathValidator

_symlinks = pytest.mark.skipif(
    sys.platform == "win32", reason="creating symlinks needs privileges on Windows"
)


@_symlinks
def test_a_path_under_a_symlinked_base_is_inside(tmp_path: Path) -> None:
    real = tmp_path / "real"
    (real / "pkg").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    # The path is spelled through the link; the base is the real directory.
    assert PathValidator.validate_path((link / "pkg").as_posix(), real) == link / "pkg"
    # And the other way round.
    assert PathValidator.validate_path((real / "pkg").as_posix(), link) == real / "pkg"


def test_outside_the_base_is_rejected_with_posix_paths(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    sibling = tmp_path / "sibling" / "x.py"

    with pytest.raises(ValidationError) as exc:
        PathValidator.validate_path(sibling.as_posix(), base)

    message = str(exc.value)
    assert "outside base directory" in message
    assert base.resolve().as_posix() in message
    assert "\\" not in message


def test_a_dotdot_escape_from_the_base_is_rejected(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    with pytest.raises(ValidationError):
        PathValidator.validate_path((base / ".." / "elsewhere").as_posix(), base)


def test_config_project_path_and_config_paths_are_resolved(tmp_path: Path) -> None:
    (tmp_path / "lib").mkdir()
    config = ProjectConfig((tmp_path / "x" / "..").as_posix())

    assert config.project_path == tmp_path.resolve()
    assert config._normalise_config_path("lib/../lib") == path_to_key(tmp_path / "lib")
    assert config._normalise_config_path("lib/*") == (tmp_path.resolve() / "lib/*").as_posix()


@_symlinks
def test_typeref_invalidation_matches_any_spelling_of_the_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    key = (path_to_key(real), "f.py", 0, 1, 0, 1, 0, "int")
    other = ("/elsewhere", "f.py", 0, 1, 0, 1, 0, "int")
    with typeref._typeref_lock:
        typeref._typeref_cache[key] = {}  # type: ignore[index]
        typeref._typeref_cache[other] = {}  # type: ignore[index]
    try:
        typeref.invalidate_project(link)
        assert key not in typeref._typeref_cache
        assert other in typeref._typeref_cache
    finally:
        with typeref._typeref_lock:
            typeref._typeref_cache.pop(other, None)  # type: ignore[call-overload]
