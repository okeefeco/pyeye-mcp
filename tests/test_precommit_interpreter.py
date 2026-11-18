"""Pre-commit runs under whatever Python 3 is available, never a fixed minor (#256, #529).

A pinned ``python3.12`` failed for contributors on other supported versions, and
broke again whenever CI's pre-commit job moved to a newer Python. Python tool
hooks run from the uv venv (``language: system`` + ``uv run --frozen``, #413), so
pre-commit builds no hook virtualenv for a specific interpreter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CONFIG = Path(__file__).resolve().parent.parent / ".pre-commit-config.yaml"


def _config() -> dict[str, Any]:
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _hooks() -> list[dict[str, Any]]:
    return [hook for repo in _config()["repos"] for hook in repo.get("hooks", [])]


def test_the_default_interpreter_is_unpinned() -> None:
    assert _config()["default_language_version"]["python"] == "python3"


def test_no_hook_pins_or_builds_its_own_python() -> None:
    for hook in _hooks():
        assert hook.get("language") != "python", hook["id"]
        assert "language_version" not in hook, hook["id"]
