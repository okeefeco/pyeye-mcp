"""Contract test: CI pipelines build from the exact locked config (#481).

Policy: the lockfile is authoritative — every environment (hooks, CI, dev,
release) builds from the identical locked dependencies, and no invocation may
silently re-resolve. The pre-commit hooks enforce this with ``uv run --frozen``
(#479); CI enforces it on its ``uv sync`` setup steps with ``--locked`` (assert
``uv.lock`` equals ``pyproject.toml``; fail on drift).

CI uses ``uv sync --locked`` (a per-step flag) rather than a workflow-level
``UV_LOCKED`` env var, because ``UV_LOCKED`` is mutually exclusive with the
``--frozen`` the pre-commit hooks carry — and the CI ``pre-commit`` job runs
those hooks, so a workflow-level ``UV_LOCKED`` makes uv abort with
"``UV_LOCKED`` cannot be used with ``--frozen``". A flag on the standalone
``uv sync`` command never shares an environment with the ``--frozen`` hook runs,
so the two can't collide.
"""

from __future__ import annotations

from pathlib import Path

_WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def test_ci_uv_sync_is_locked():
    """Every ``uv sync`` in a workflow must carry ``--locked`` (no bare sync)."""
    offenders = []
    for wf in sorted(_WORKFLOWS.glob("*.yml")) + sorted(_WORKFLOWS.glob("*.yaml")):
        for lineno, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            if "uv sync" in line and "--locked" not in line:
                offenders.append(f"{wf.name}:{lineno}")
    assert not offenders, (
        "CI `uv sync` must be `uv sync --locked` so the pipeline asserts the lock "
        f"is current and never re-resolves (#481): {offenders}"
    )
