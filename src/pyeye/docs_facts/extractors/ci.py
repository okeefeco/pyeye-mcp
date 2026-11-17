"""CI and packaging facts: the coverage threshold and the supported Pythons.

- ``ci.coverage_threshold``: ``--cov-fail-under`` in pytest's ``addopts``
  (``pyproject.toml``). Every ``--cov-fail-under`` in ``ci.yml`` must agree,
  or extraction fails: two thresholds would be two facts with one name.
- ``ci.python_versions``: the full ``test-main`` matrix in ``ci.yml``.
- ``project.python_versions`` / ``project.requires_python``: the trove
  classifiers and ``requires-python`` in ``pyproject.toml``. The matrix must
  equal the classifiers, and ``requires-python`` must be ``>=`` the oldest of
  them, or extraction fails: what CI tests is what the package claims.

``ci.yml`` is read with a pattern, not a YAML parser, so no dependency is added;
each pattern must match, or extraction fails rather than yielding nothing.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterator
from pathlib import Path

from ..facts import Bindable, Fact

PREFIXES = ("ci", "project")

CI_WORKFLOW = ".github/workflows/ci.yml"
_FAIL_UNDER = re.compile(r"--cov-fail-under=(\d+)")
_MATRIX = re.compile(r"^\s*python-version:\s*\[([^\]]*)\]", re.MULTILINE)
_CLASSIFIER = re.compile(r"Programming Language :: Python :: (3\.\d+)$")


class ExtractionError(ValueError):
    """A source no longer has the shape the extractor reads."""


def extract(root: Path) -> Iterator[Bindable]:
    """Yield the CI and packaging facts."""
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    addopts = " ".join(pyproject["tool"]["pytest"]["ini_options"]["addopts"])
    thresholds = _FAIL_UNDER.findall(addopts)
    if len(thresholds) != 1:
        raise ExtractionError("pytest addopts must set --cov-fail-under exactly once")
    threshold = int(thresholds[0])

    workflow = (root / CI_WORKFLOW).read_text(encoding="utf-8")
    others = {int(t) for t in _FAIL_UNDER.findall(workflow)}
    if others - {threshold}:
        raise ExtractionError(
            f"{CI_WORKFLOW} uses --cov-fail-under {sorted(others)}, pyproject {threshold}"
        )
    matrices = _MATRIX.findall(workflow)
    if len(matrices) != 1:
        raise ExtractionError(f"{CI_WORKFLOW} must have exactly one python-version list")
    versions = [v.strip().strip("'\"") for v in matrices[0].split(",") if v.strip()]

    classifiers = [
        m.group(1)
        for c in pyproject["project"].get("classifiers", [])
        if (m := _CLASSIFIER.search(c))
    ]
    requires = pyproject["project"]["requires-python"]
    if versions != classifiers:
        raise ExtractionError(
            f"{CI_WORKFLOW} tests Python {versions}, but pyproject's classifiers claim "
            f"{classifiers}"
        )
    if classifiers and requires != f">={classifiers[0]}":
        raise ExtractionError(
            f"requires-python is {requires!r}, but the oldest classifier is {classifiers[0]}"
        )

    yield Fact("ci.coverage_threshold", threshold, f"{threshold}%")
    yield Fact("ci.python_versions", versions, ", ".join(versions))
    yield Fact("project.python_versions", classifiers, ", ".join(classifiers))
    yield Fact("project.requires_python", requires, f"`{requires}`")
