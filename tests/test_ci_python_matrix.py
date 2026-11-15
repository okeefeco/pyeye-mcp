"""The CI Python matrix, its docs-only dummy and the pyproject classifiers agree (#543).

Adding a Python version touches three places: the ``test-pr`` and ``test-main``
matrices in ``ci.yml``, the ``test-pr-dummy`` matrix that reports the same check
names on docs-only PRs, and the ``Programming Language :: Python :: 3.X``
classifiers. These tests keep them in step. Required-check reporting itself is
covered by ``test_ci_merge_group.py``.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_PYPROJECT = _ROOT / "pyproject.toml"


def _jobs() -> dict[str, Any]:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))["jobs"]


def _legs(job: dict[str, Any]) -> set[tuple[str, str]]:
    return {(leg["os"], str(leg["python-version"])) for leg in job["strategy"]["matrix"]["include"]}


def _classified_versions() -> set[str]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    pattern = re.compile(r"^Programming Language :: Python :: (3\.\d+)$")
    return {m.group(1) for c in data["project"]["classifiers"] if (m := pattern.match(c))}


def test_dummy_matrix_mirrors_test_pr() -> None:
    """Docs-only PRs must report exactly the names the real PR matrix reports."""
    jobs = _jobs()
    assert _legs(jobs["test-pr-dummy"]) == _legs(jobs["test-pr"])


def test_linux_pr_legs_cover_every_classified_version() -> None:
    """The PR matrix tests every classified Python on Linux (the cheap runner)."""
    linux = {py for os_, py in _legs(_jobs()["test-pr"]) if os_ == "ubuntu-latest"}
    assert linux == _classified_versions()


def test_main_matrix_covers_every_classified_version_on_every_os() -> None:
    matrix = _jobs()["test-main"]["strategy"]["matrix"]
    assert {str(v) for v in matrix["python-version"]} == _classified_versions()
    assert set(matrix["os"]) == {"ubuntu-latest", "windows-latest", "macos-latest"}


def test_newest_version_runs_on_every_os_in_pr_matrix() -> None:
    """The newest classified Python is exercised on every OS on PRs (#543: watchdog on macOS)."""
    newest = max(_classified_versions(), key=lambda v: tuple(map(int, v.split("."))))
    oses = {os_ for os_, py in _legs(_jobs()["test-pr"]) if py == newest}
    assert oses == {"ubuntu-latest", "windows-latest", "macos-latest"}
    assert newest == "3.14"
