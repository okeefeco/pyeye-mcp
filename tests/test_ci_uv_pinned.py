"""Contract test: CI pipelines build from the exact locked config (#481).

Policy: the lockfile is authoritative — every environment (hooks, CI, dev,
release) builds from the identical locked dependencies, and no invocation may
silently re-resolve. The hooks enforce this with ``uv run --frozen`` (#479);
CI enforces it with ``UV_LOCKED`` (the env-var form of ``--locked``), set at the
workflow level so every ``uv`` step — sync, run, current or future — asserts the
lock equals ``pyproject.toml`` and fails loudly on drift.

Setting it once per workflow (rather than a per-line flag) means a newly added
``uv`` step cannot silently opt out — the policy can't erode.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _uses_uv(text: str) -> bool:
    return "uv sync" in text or "uv run" in text or "uv lock" in text


def test_uv_workflows_pin_locked_at_workflow_level():
    """Any workflow invoking uv must declare ``env.UV_LOCKED`` at the top level."""
    offenders = []
    for wf in sorted(_WORKFLOWS.glob("*.yml")) + sorted(_WORKFLOWS.glob("*.yaml")):
        text = wf.read_text(encoding="utf-8")
        if not _uses_uv(text):
            continue
        data = yaml.safe_load(text) or {}
        top_env = data.get("env") or {}
        if "UV_LOCKED" not in top_env:
            offenders.append(wf.name)
    assert not offenders, (
        "workflows invoking uv must set top-level `env: UV_LOCKED` so every uv "
        f"step honors the lock (#481): {offenders}"
    )
