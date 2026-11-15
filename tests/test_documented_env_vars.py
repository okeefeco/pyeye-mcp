"""Every PYEYE_* variable named in the user docs must actually take effect (#556).

The docs had drifted badly:

* package configuration through ``PYEYE_PACKAGES`` / ``PYEYE_NAMESPACE_*``,
  given in three incompatible formats, which nothing reads;
* misspelt names (``PYEYE_DEBOUNCE``, ``PYEYE_WORKERS``, ``PYEYE_TIMEOUT``);
* knobs that don't exist (``PYEYE_CACHE_ENABLED``, ``PYEYE_CACHE_MEMORY_MB``, …);
* real variables loaded into ``PerformanceSettings`` but never *used*
  (``PYEYE_MAX_WORKERS``, ``PYEYE_ANALYSIS_TIMEOUT``, …).

So "live" here means more than "read by ``src/``": for a variable that
``settings.py`` loads into an attribute, that attribute must be used somewhere
else in ``src/``.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src" / "pyeye"
_SETTINGS = _SRC / "settings.py"
# Includes lowercase suffixes, e.g. the documented ``PYEYE_NAMESPACE_company``.
_NAME = re.compile(r"\bPYEYE_[A-Za-z][A-Za-z0-9_]*[A-Za-z0-9]")

# User- and contributor-facing docs. Design specs (docs/superpowers) and the
# decision log are records of proposals and history, not instructions.
_DOCS = sorted(
    [
        _ROOT / "README.md",
        _ROOT / "DOCUMENTATION.md",
        _ROOT / "CONTRIBUTING.md",
        _ROOT / "SECURITY.md",
        *(_ROOT / "docs").glob("*.md"),
        *(_ROOT / "docs" / "source").rglob("*.rst"),
        *(_ROOT / ".claude" / "instructions").glob("*.md"),
    ]
)


def _settings_attributes() -> dict[str, str]:
    """``PYEYE_*`` name -> the ``PerformanceSettings`` attribute it sets."""
    text = _SETTINGS.read_text(encoding="utf-8")
    pattern = r"self\.(\w+)\s*:\s*[\w\[\], |]+=\s*self\._get_\w+_env\(\s*\"(PYEYE_\w+)\""
    return {name: attr for attr, name in re.findall(pattern, text)}


def _src_text_excluding_settings() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in _SRC.rglob("*.py") if p != _SETTINGS)


def live_env_vars() -> set[str]:
    """Variables that change pyeye's behaviour."""
    other_src = _src_text_excluding_settings()
    live = set(_NAME.findall(other_src))  # read directly outside settings.py
    for name, attr in _settings_attributes().items():
        if re.search(rf"\.{attr}\b", other_src):
            live.add(name)
    return live


def documented_env_vars() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in _DOCS:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for name in _NAME.findall(line):
                found.setdefault(name, []).append(f"{path.relative_to(_ROOT).as_posix()}:{n}")
    return found


def test_settings_parser_finds_every_setting():
    """Guard the parser: if it silently matched nothing, every check would pass."""
    attrs = _settings_attributes()
    assert len(attrs) >= 10, attrs
    assert attrs["PYEYE_CACHE_TTL"] == "cache_ttl"
    assert attrs["PYEYE_WATCHER_DEBOUNCE"] == "watcher_debounce"


def test_liveness_distinguishes_used_from_merely_loaded():
    live = live_env_vars()
    assert {"PYEYE_CACHE_TTL", "PYEYE_MAX_PROJECTS", "PYEYE_LOG_LEVEL"} <= live
    # Loaded by settings.py but consumed nowhere (#556 follow-up issue).
    assert "PYEYE_MAX_WORKERS" not in live


def _deprecated_env_vars() -> set[str]:
    """Names ``settings.DEPRECATED_ENV_VARS`` lists (parsed, so no import side effects)."""
    text = _SETTINGS.read_text(encoding="utf-8")
    block = text.split("DEPRECATED_ENV_VARS", 1)[1].split("}", 1)[0]
    return set(re.findall(r"\"(PYEYE_\w+)\"\s*:", block))


def _undeprecated_mentions() -> dict[str, list[str]]:
    """Doc lines naming a deprecated variable without saying it is deprecated."""
    deprecated = _deprecated_env_vars()
    found: dict[str, list[str]] = {}
    for path in _DOCS:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for name in set(_NAME.findall(line)) & deprecated:
                if "deprecated" not in line.lower():
                    found.setdefault(name, []).append(f"{path.relative_to(_ROOT).as_posix()}:{n}")
    return found


def test_deprecated_env_vars_parser():
    deprecated = _deprecated_env_vars()
    assert {"PYEYE_MAX_WORKERS", "PYEYE_ENABLE_CONNECTION_POOLING", "PYEYE_POOL_TTL"} <= deprecated
    assert "PYEYE_CACHE_TTL" not in deprecated


def test_every_documented_env_var_takes_effect():
    """A documented variable must work, or (v2.x) be deprecated and say so."""
    live = live_env_vars() | _deprecated_env_vars()
    dead = {name: where for name, where in documented_env_vars().items() if name not in live}
    assert not dead, (
        "docs name PYEYE_* variables that pyeye never reads or never uses; "
        f"remove them or make them work: {dead}"
    )


def test_deprecated_env_vars_are_documented_as_deprecated():
    """Every doc line naming a deprecated variable must say "deprecated" (#628)."""
    found = _undeprecated_mentions()
    assert not found, f"mark these lines as deprecated (no effect, removed in v3.0): {found}"
