"""Every module pyeye imports at runtime comes with a normal install (#1094).

PyYAML reached this repo only through dev tools (bandit, commitizen,
detect-secrets, mkdocs), so the suite always had it, while a user install
(pip, uvx, the plugin) didn't: a documented ``.pyeye.yaml`` config failed to
load there, and CI never saw it. These tests make that class of gap fail in CI:

- every third-party module ``src/pyeye`` imports must be provided by a declared
  ``[project].dependencies`` entry, directly or through what that entry itself
  requires (read from installed package metadata);
- a ``.pyeye.yaml`` config loads through the runtime path, with no skip when
  PyYAML is missing;
- with ``yaml`` unimportable, loading a YAML config records a load error that
  names the cause, rather than losing the config silently.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from importlib.metadata import PackageNotFoundError, packages_distributions, requires
from pathlib import Path

import pytest

from pyeye.config import ProjectConfig

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "pyeye"


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement(spec: str) -> tuple[str, set[str], str]:
    """``(name, extras, marker)`` of a requirement string such as ``mcp[cli]>=2; ...``."""
    spec, _, marker = spec.partition(";")
    match = re.match(r"\s*([A-Za-z0-9._-]+)\s*(?:\[([^\]]*)\])?", spec)
    assert match, spec
    extras = {_canonical(e) for e in (match.group(2) or "").split(",") if e.strip()}
    return _canonical(match.group(1)), extras, marker.strip()


def _declared() -> list[str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return list(project["dependencies"])


def _runtime_closure() -> set[str]:
    """Canonical names of every distribution a runtime install brings in.

    Starts from ``[project].dependencies`` and follows each one's own
    requirements, with the extras asked for. A requirement whose marker names
    an extra not asked for is skipped; other markers are taken as true, which
    over-approximates but never hides a declared dependency.
    """
    seen: set[str] = set()
    queue = [_requirement(spec)[:2] for spec in _declared()]
    while queue:
        name, extras = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            reqs = requires(name) or []
        except PackageNotFoundError:
            continue
        for spec in reqs:
            child, child_extras, marker = _requirement(spec)
            wanted = re.findall(r"extra\s*==\s*['\"]([^'\"]+)['\"]", marker)
            if wanted and not {_canonical(w) for w in wanted} & extras:
                continue
            queue.append((child, child_extras))
    return seen


def _third_party_imports() -> dict[str, list[str]]:
    """Top-level module -> files under ``src/pyeye`` that import it (absolute imports)."""
    found: dict[str, list[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top in sys.stdlib_module_names or top in ("pyeye", "__future__"):
                    continue
                found.setdefault(top, []).append(path.relative_to(ROOT).as_posix())
    return found


class TestDeclaredDependencies:
    def test_pyyaml_is_a_runtime_dependency(self) -> None:
        """``.pyeye.yaml`` is documented project config, so PyYAML ships with pyeye."""
        assert "pyyaml" in {_requirement(spec)[0] for spec in _declared()}

    def test_every_runtime_import_comes_with_an_install(self) -> None:
        """A module only dev tools bring in fails here, not in a user's install."""
        closure = _runtime_closure()
        providers = packages_distributions()
        missing = {
            module: files
            for module, files in _third_party_imports().items()
            if not {_canonical(d) for d in providers.get(module, [])} & closure
        }
        assert not missing, (
            "src/pyeye imports modules no [project].dependencies entry provides, "
            f"directly or through its requirements: {missing}"
        )

    def test_the_import_scan_sees_the_known_imports(self) -> None:
        """Guard the scan: an empty one would make the check above pass vacuously."""
        imports = _third_party_imports()

        assert {"jedi", "mcp", "watchdog", "yaml"} <= set(imports)
        # The one data-file reader (#1091) holds the import; config.py reads through it.
        assert "pyeye/_data_files.py" in "".join(imports["yaml"])

    def test_the_closure_follows_requirements(self) -> None:
        """``parso`` arrives through ``jedi``; ``pyyaml`` through nothing but itself."""
        closure = _runtime_closure()

        assert {"jedi", "parso", "mcp"} <= closure


class TestYamlConfig:
    def _project(self, tmp_path: Path) -> Path:
        (tmp_path / ".pyeye.yaml").write_text("pyeye:\n  cache_ttl: 123\n", encoding="utf-8")
        return tmp_path

    def test_a_yaml_config_loads_on_the_runtime_path(self, tmp_path: Path) -> None:
        """No importorskip: if PyYAML is missing, this fails rather than skips."""
        config = ProjectConfig(str(self._project(tmp_path)))

        assert config.load_errors == []
        assert config.config["cache_ttl"] == 123

    def test_without_yaml_the_failure_is_recorded_with_its_cause(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If ``yaml`` were ever unimportable, the config is reported lost, never silently."""
        monkeypatch.setitem(sys.modules, "yaml", None)  # makes `import yaml` raise

        config = ProjectConfig(str(self._project(tmp_path)))

        assert "cache_ttl" not in config.config or config.config["cache_ttl"] != 123
        assert any(
            ".pyeye.yaml" in e and "yaml" in e for e in config.load_errors
        ), config.load_errors
