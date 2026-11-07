"""Contract test: local environment setup builds from the exact locked config (#573).

Companion to ``tests/test_ci_uv_pinned.py`` (#481). The lockfile is
authoritative, and each context pins how strictly it holds to it:

* **Hooks** use ``uv run --frozen`` (#479).
* **CI** uses ``uv sync --locked``: assert ``uv.lock`` matches ``pyproject.toml``
  and fail on drift.
* **Local setup** uses ``uv sync --frozen``: install from ``uv.lock`` as-is and
  never re-resolve. That way setup never blocks and never rewrites the lock,
  including behind a PyPI mirror. Drift is still caught by CI.

Bare ``uv sync`` may re-resolve and rewrite ``uv.lock``, so the setup script
and every doc that tells a human or Claude how to build an environment must
carry ``--frozen``. ``--locked`` is also accepted, because these docs describe
the CI policy too. Prose that names bare ``uv sync`` in order to forbid it
(written as "bare `uv sync`") is allowed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# Every file that prescribes how to set up a local environment.
_LOCAL_SETUP_FILES = sorted(
    [
        _ROOT / "setup.sh",
        _ROOT / "CONTRIBUTING.md",
        _ROOT / "DOCUMENTATION.md",
        _ROOT / "docs" / "TROUBLESHOOTING.md",
        _ROOT / "docs" / "RELEASE.md",
        *(_ROOT / "docs" / "source").glob("*.rst"),
        *(_ROOT / ".claude" / "instructions").glob("*.md"),
    ]
)

# `uv sync` plus the flag run that follows it, e.g. `uv sync --frozen --group docs`.
_UV_SYNC = re.compile(r"uv sync(?P<flags>(?:\s+--?[\w-]+(?:[ =](?!-)[\w.-]+)?)*)")


def _unpinned_syncs(text: str) -> list[int]:
    """Return 1-based line numbers of `uv sync` uses lacking --frozen/--locked."""
    offenders = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for match in _UV_SYNC.finditer(line):
            flags = match.group("flags").split()
            if "--frozen" in flags or "--locked" in flags:
                continue
            if re.search(r"bare `?$", line[: match.start()]):
                continue  # prose forbidding bare `uv sync`
            offenders.append(lineno)
    return offenders


@pytest.mark.parametrize(
    ("line", "flagged"),
    [
        ("uv sync", True),
        ("   uv sync", True),
        ("run `uv sync` first", True),
        ("uv sync --group docs", True),
        ("uv sync --frozen", False),
        ("uv sync --frozen --group docs", False),
        ("uv sync --group docs --frozen", False),
        ("CI pins `uv sync --locked`", False),
        ("NEVER use bare `uv sync` locally", False),
    ],
)
def test_matcher(line: str, flagged: bool):
    """The scanner flags bare syncs and accepts pinned or explicitly-forbidden ones."""
    assert bool(_unpinned_syncs(line)) is flagged


def test_local_setup_files_exist():
    """Guard against the scan silently covering nothing after a file move."""
    missing = [p.relative_to(_ROOT).as_posix() for p in _LOCAL_SETUP_FILES if not p.is_file()]
    assert not missing, f"local-setup files moved or deleted; update this test: {missing}"
    assert any(p.suffix == ".rst" for p in _LOCAL_SETUP_FILES)
    assert any(p.parent.name == "instructions" for p in _LOCAL_SETUP_FILES)


def test_local_uv_sync_is_frozen():
    """Every `uv sync` in local-setup docs and scripts must be pinned (#573)."""
    offenders = [
        f"{path.relative_to(_ROOT).as_posix()}:{lineno}"
        for path in _LOCAL_SETUP_FILES
        for lineno in _unpinned_syncs(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "Local setup must use `uv sync --frozen` (CI: `--locked`) so it never "
        f"re-resolves or rewrites uv.lock (#573): {offenders}"
    )
