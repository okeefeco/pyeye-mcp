"""Repo-supplied paths are refused lexically before any filesystem call (#1048).

On Windows, ``is_dir()`` or ``resolve()`` on ``\\\\host\\share`` opens an SMB
connection to that host, which can leak the user's NTLM credentials. A path a
repository supplies (a ``.pth`` line in its ``.venv``, a declared dependency, a
``.pyeye.json`` or ``[tool.pyright]`` entry) is checked by
:func:`pyeye.path_utils.network_path`, a pure string test, before anything
touches it.

The Windows cases run on every platform: the predicate takes the platform as an
argument, and the call sites are exercised with the filesystem patched so a
call that reaches it fails the test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye import path_utils
from pyeye.path_utils import network_path

REFUSED_ON_WINDOWS = [
    r"\\attacker.example\share\pkg",  # UNC
    "//attacker.example/share/pkg",  # UNC, forward slashes
    r"\\attacker.example",  # an incomplete UNC still names a host
    r"\\?\UNC\attacker.example\share",  # extended UNC
    r"\\?\C:\pkg",  # extended-length (device namespace)
    r"\\.\pipe\x",  # device
    "//?/C:/pkg",
    "C:pkg",  # drive-relative: that drive's cwd, which the server doesn't own
    r"\pkg",  # root-relative: the current drive, a share if the cwd is on one
]

ALLOWED_ON_WINDOWS = [r"C:\Users\me\pkg", "C:/Users/me/pkg", "pkg", r"..\sibling", "./src"]


class TestThePredicate:
    @pytest.mark.parametrize("path", REFUSED_ON_WINDOWS)
    def test_network_device_and_cwd_relative_paths_are_refused(self, path: str) -> None:
        reason = network_path(path, windows=True)

        assert reason is not None and reason, path

    @pytest.mark.parametrize("path", ALLOWED_ON_WINDOWS)
    def test_local_and_relative_paths_pass(self, path: str) -> None:
        assert network_path(path, windows=True) is None

    @pytest.mark.parametrize("path", [*REFUSED_ON_WINDOWS, "/home/me/pkg", "pkg"])
    def test_on_posix_nothing_is_a_network_path(self, path: str) -> None:
        """``//x`` is local on POSIX and ``\\`` is a filename character there."""
        assert network_path(path, windows=False) is None

    def test_a_path_object_is_accepted(self) -> None:
        assert network_path(Path("pkg"), windows=True) is None

    def test_it_never_touches_the_filesystem(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*_: Any, **__: Any) -> Any:
            raise AssertionError("network_path touched the filesystem")

        for method in ("resolve", "exists", "is_dir", "stat", "absolute"):
            monkeypatch.setattr(Path, method, boom)

        for path in [*REFUSED_ON_WINDOWS, *ALLOWED_ON_WINDOWS]:
            network_path(path, windows=True)

    def test_the_default_is_this_platform(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(path_utils, "_ON_WINDOWS", True)
        assert network_path(r"\\h\s") is not None
        monkeypatch.setattr(path_utils, "_ON_WINDOWS", False)
        assert network_path(r"\\h\s") is None


HOST = "attacker.example"
UNC = rf"\\{HOST}\share\pkg"


@pytest.fixture
def windows_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(path_utils, "_ON_WINDOWS", True)


@pytest.fixture
def touched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every filesystem call on a path naming the attacker's host, recorded."""
    calls: list[str] = []
    real_open = open

    def spy(name: str) -> None:
        real = getattr(Path, name)

        def wrapper(self: Path, *args: Any, **kwargs: Any) -> Any:
            if HOST in str(self) or any(HOST in str(a) for a in args):  # a glob's pattern too
                calls.append(f"{name}({self}, {args})")
            return real(self, *args, **kwargs)

        monkeypatch.setattr(Path, name, wrapper)

    for name in ("exists", "is_dir", "is_file", "resolve", "stat", "glob", "iterdir", "open"):
        spy(name)

    def spy_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if HOST in str(file):
            calls.append(f"open({file})")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", spy_open)
    return calls


def json_dumps(data: Any) -> str:
    import json

    return json.dumps(data)


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")


@pytest.mark.usefixtures("windows_rules")
class TestEnvironmentPthLines:
    def test_a_unc_line_is_skipped_before_any_lookup(
        self, tmp_path: Path, touched: list[str]
    ) -> None:
        from pyeye.environment import site_paths

        env = tmp_path / ".venv"
        (env / "Lib/site-packages/local_pkg").mkdir(parents=True)
        (env / "Lib/site-packages/evil.pth").write_text(f"{UNC}\nlocal_pkg\n", encoding="utf-8")

        paths = site_paths(env)

        assert touched == []
        assert not any(HOST in p for p in paths)
        assert any(p.endswith("site-packages/local_pkg") for p in paths)


@pytest.mark.usefixtures("windows_rules")
class TestDeclaredDependencies:
    @pytest.mark.parametrize(
        "pyproject",
        [
            f"[tool.uv.sources]\nevil = {{ path = '{UNC}' }}\n",
            f"[tool.uv.workspace]\nmembers = ['{UNC}']\n",
            f"[tool.poetry.dependencies]\nevil = {{ path = '{UNC}' }}\n",
            # file: URLs whose path is a UNC or a root-relative path on Windows
            f"[project]\nname = 'p'\ndependencies = ['evil @ file:{UNC}']\n",
            f"[project]\nname = 'p'\ndependencies = ['evil @ file:////{HOST}/share/pkg']\n",
            # %5C is a backslash: the check runs on the decoded path
            f"[project]\nname = 'p'\ndependencies = ['evil @ file:%5C%5C{HOST}%5Cshare']\n",
            f"[tool.uv.workspace]\nmembers = ['{UNC}\\\\*']\n",  # a glob is refused before it runs
        ],
        ids=[
            "uv-source",
            "uv-workspace",
            "poetry",
            "file-url-unc",
            "file-url-slashes",
            "file-url-escaped",
            "uv-workspace-glob",
        ],
    )
    def test_a_network_target_is_skipped_before_any_lookup(
        self, tmp_path: Path, touched: list[str], pyproject: str
    ) -> None:
        from pyeye.declared_deps import declared_path_dependencies

        _write(tmp_path, {"pyproject.toml": pyproject})

        found = declared_path_dependencies(tmp_path)

        assert touched == []
        assert not any(HOST in root for root, _ in found)

    def test_a_local_declaration_still_counts(self, tmp_path: Path) -> None:
        from pyeye.declared_deps import declared_path_dependencies

        _write(
            tmp_path,
            {
                "pyproject.toml": "[tool.uv.sources]\nlib = { path = 'lib' }\n",
                "lib/lib/__init__.py": "",
            },
        )

        assert [r for _, r in declared_path_dependencies(tmp_path)] == ["uv_source"]


@pytest.mark.usefixtures("windows_rules")
class TestProjectConfigFiles:
    @pytest.mark.parametrize(
        ("files", "scope"),
        [
            ({".pyeye.json": json_dumps({"packages": [UNC, "lib"]})}, "packages"),
            ({".pyeye.json": json_dumps({"namespaces": {"ns": [UNC]}})}, "namespace:ns"),
            ({".pyeye.json": json_dumps({"standalone": {"dirs": [UNC]}})}, "standalone"),
            ({".pyeye.override.json": json_dumps({"packages": [UNC]})}, "packages"),
            (
                {"pyproject.toml": f"[tool.pyeye]\npackages = ['{UNC}']\n"},
                "packages",
            ),
        ],
        ids=["packages", "namespaces", "standalone", "override", "pyproject"],
    )
    def test_an_entry_is_refused_and_reported(
        self, tmp_path: Path, touched: list[str], files: dict[str, str], scope: str
    ) -> None:
        from pyeye.config import ProjectConfig

        _write(tmp_path, {"lib/__init__.py": "", **files})

        config = ProjectConfig(tmp_path.as_posix())
        packages = config.get_package_paths()
        namespaces = config.get_namespaces()
        standalone = config.get_standalone_paths()
        rejected = config.rejected_paths() or []

        assert touched == []
        assert not any(HOST in p for p in packages)
        assert not any(HOST in d for dirs in namespaces.values() for d in dirs)
        assert not any(HOST in str(d) for d in standalone)
        assert [(r["scope"], r["path"]) for r in rejected] == [(scope, UNC)]
        assert "network" in rejected[0]["detail"]

    def test_the_saved_layer_keeps_the_entry_as_written(self, tmp_path: Path) -> None:
        """A save must not silently delete what the user wrote (#1038)."""
        from pyeye.config import ProjectConfig

        _write(tmp_path, {".pyeye.json": json_dumps({"packages": [UNC]})})

        config = ProjectConfig(tmp_path.as_posix())

        assert config._project_layer["packages"] == [UNC]

    def test_a_configured_environment_is_refused(self, tmp_path: Path, touched: list[str]) -> None:
        from pyeye.config import ProjectConfig
        from pyeye.environment import discover

        _write(tmp_path, {".pyeye.json": json_dumps({"environment": UNC})})

        config = ProjectConfig(tmp_path.as_posix())
        env = discover(tmp_path, config.config.get("environment"))

        assert touched == []
        assert env.path is None or HOST not in env.path.as_posix()

    def test_pyright_extra_paths_and_build_layouts(
        self, tmp_path: Path, touched: list[str]
    ) -> None:
        from pyeye.config import ProjectConfig

        _write(
            tmp_path,
            {
                "pyproject.toml": (
                    f"[tool.pyright]\nextraPaths = [7, '{UNC}']\n"
                    f"[tool.setuptools.packages.find]\nwhere = ['{UNC}']\n"
                ),
            },
        )

        config = ProjectConfig(tmp_path.as_posix())
        packages = config.get_package_paths()

        assert touched == []
        assert config.load_errors == []  # a non-string entry is skipped, not an error
        assert not any(HOST in p for p in packages)

    def test_the_users_global_config_is_not_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The user's own config is their choice, not the repository's (ruled 2026-11-20)."""
        from pyeye.config import ProjectConfig

        home = tmp_path / "home"
        _write(home, {".config/pyeye/config.json": json_dumps({"packages": [UNC]})})
        monkeypatch.setattr(Path, "home", lambda: home)
        project = tmp_path / "proj"
        project.mkdir()

        config = ProjectConfig(project.as_posix())

        assert UNC in config.config.get("packages", [])
