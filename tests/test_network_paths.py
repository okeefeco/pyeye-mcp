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


#: POSIX reads ``//host/...`` as absolute, so a lookup on it really happens on Linux.
SLASHED = f"//{HOST}/share/wt"


@pytest.mark.usefixtures("windows_rules")
class TestGitPointers:
    """A repository's ``.gitmodules`` and ``.git`` file are read on every walk (#1053 review)."""

    @pytest.mark.parametrize("value", [SLASHED, f'"{UNC}"', UNC])
    def test_a_gitmodules_path_is_skipped_before_any_lookup(
        self, tmp_path: Path, touched: list[str], value: str
    ) -> None:
        from pyeye.async_utils import _declared_submodules

        _write(tmp_path, {".gitmodules": f'[submodule "x"]\n\tpath = {value}\n\tpath = lib\n'})

        declared = _declared_submodules(tmp_path)

        assert touched == []
        assert not any(HOST in d for d in declared)
        assert any(d.endswith("/lib") for d in declared)  # a local one still counts

    @pytest.mark.parametrize(
        "gitdir",
        [
            "/elsewhere/.git/worktrees/feature",  # root-relative on Windows (the fixtures' form)
            f"//{HOST}/share/.git/worktrees/feature",  # a share
        ],
    )
    def test_a_refused_worktree_shaped_gitdir_is_still_a_worktree(
        self, tmp_path: Path, touched: list[str], gitdir: str
    ) -> None:
        """Refused means not looked up, NOT "a normal source tree": the pointer's layout decides.

        The same lexical rule as a pruned worktree's gitdir (``…/worktrees/<name>``), so
        a duplicate checkout is still kept out of the walk (#1053 CI, Windows).
        """
        from pyeye.async_utils import _is_linked_worktree

        _write(tmp_path, {".git": f"gitdir: {gitdir}\n"})

        assert _is_linked_worktree(tmp_path) is True
        assert touched == []

    def test_a_gitdir_pointer_is_not_followed(self, tmp_path: Path, touched: list[str]) -> None:
        from pyeye.async_utils import _is_linked_worktree

        _write(tmp_path, {".git": f"gitdir: {SLASHED}\n"})

        assert _is_linked_worktree(tmp_path) is False
        assert touched == []


@pytest.mark.usefixtures("windows_rules")
class TestHomeExpansion:
    """``~`` is expanded before the lookup, so it is checked expanded too (#1053 review, L1)."""

    @pytest.fixture
    def roaming_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", f"//{HOST}/home")
        monkeypatch.setenv("USERPROFILE", rf"\\{HOST}\home")

    @pytest.mark.usefixtures("roaming_home")
    def test_the_predicate_refuses_an_expansion_onto_a_share(self) -> None:
        from pyeye.path_utils import repo_path_refusal

        assert repo_path_refusal("~/lib") is not None
        assert repo_path_refusal("lib") is None

    def test_a_local_home_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pyeye.path_utils import repo_path_refusal

        monkeypatch.setenv("HOME", "C:/Users/me")
        monkeypatch.setenv("USERPROFILE", r"C:\Users\me")

        assert repo_path_refusal("~/lib") is None

    @pytest.mark.usefixtures("roaming_home")
    def test_a_declared_dependency_under_home(self, tmp_path: Path, touched: list[str]) -> None:
        from pyeye.declared_deps import declared_path_dependencies

        _write(tmp_path, {"pyproject.toml": "[tool.uv.sources]\nlib = { path = '~/lib' }\n"})

        assert declared_path_dependencies(tmp_path) == []
        assert touched == []

    @pytest.mark.usefixtures("roaming_home")
    def test_a_config_package_under_home(
        self, tmp_path: Path, touched: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The user's own global config lives in their home: that lookup is theirs, not the repo's."""
        from pyeye.config import ProjectConfig

        monkeypatch.setattr(Path, "home", lambda: tmp_path / "local-home")
        _write(tmp_path, {".pyeye.json": json_dumps({"packages": ["~/lib"]})})

        config = ProjectConfig(tmp_path.as_posix())
        config.get_package_paths()

        assert touched == []
        assert [r["path"] for r in config.rejected_paths() or []] == ["~/lib"]


@pytest.fixture
def searched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every import search path naming the host that Jedi hands to its inference subprocess.

    pyeye's Jedi (``SameEnvironment``) looks modules up in a subprocess, out of
    an in-process spy's reach. ``Importer.follow`` passes the whole search path
    through ``import_module_by_names``, so that is where it is seen.
    """
    import jedi.inference.imports as jedi_imports

    calls: list[str] = []
    real = jedi_imports.import_module_by_names

    def spy(
        inference_state: Any, import_names: Any, sys_path: Any = None, *a: Any, **kw: Any
    ) -> Any:
        calls.extend(str(p) for p in sys_path or () if HOST in str(p))
        return real(inference_state, import_names, sys_path, *a, **kw)

    monkeypatch.setattr(jedi_imports, "import_module_by_names", spy)
    return calls


@pytest.mark.usefixtures("windows_rules")
class TestJediSysPathModifications:
    """Jedi adds a repo file's own ``sys.path`` changes to its import search (#1053 review, H2).

    pyeye filters them through :func:`~pyeye.path_utils.repo_path_refusal`, in
    a wrapper of ``jedi.inference.sys_path.check_sys_path_modifications``
    installed with the other Jedi patches (``pyeye._parso_cache``). Verified
    against Jedi 0.20.1.
    """

    def test_the_jedi_internal_still_exists_and_is_wrapped(self) -> None:
        import jedi.inference.sys_path as jedi_sys_path

        from pyeye import _parso_cache

        assert _parso_cache._is_marked(jedi_sys_path.check_sys_path_modifications)

    @pytest.mark.asyncio
    async def test_an_inline_sys_path_entry_is_never_searched(
        self, tmp_path: Path, searched: list[str]
    ) -> None:
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer
        from pyeye.mcp.operations.resolve import resolve_at

        _write(
            tmp_path,
            {
                "app/__init__.py": "",
                "app/m.py": f"import sys\nsys.path.insert(0, '//{HOST}/share')\nimport evilmod\n",
            },
        )

        await resolve_at(
            (tmp_path / "app/m.py").as_posix(), 3, 8, JediAnalyzer(tmp_path.as_posix())
        )

        assert searched == []

    @pytest.mark.asyncio
    async def test_a_buildout_scripts_sys_path_is_never_searched(
        self, tmp_path: Path, searched: list[str]
    ) -> None:
        """``buildout.cfg`` plus ``bin/*`` scripts: Jedi reads their ``sys.path`` lines too."""
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer
        from pyeye.mcp.operations.resolve import resolve_at

        _write(
            tmp_path,
            {
                "buildout.cfg": "[buildout]\n",
                "bin/app": f"#!/usr/bin/python\nimport sys\nsys.path[0:0] = ['//{HOST}/share']\n",
                "app/__init__.py": "",
                "app/m.py": "import evilmod\n",
            },
        )

        await resolve_at(
            (tmp_path / "app/m.py").as_posix(), 1, 8, JediAnalyzer(tmp_path.as_posix())
        )

        assert searched == []


def test_a_local_inline_sys_path_entry_still_counts(tmp_path: Path) -> None:
    """Only network paths are dropped: a repo's local ``sys.path`` change is Jedi's normal behaviour."""
    import jedi

    _write(
        tmp_path,
        {
            "vendor/vendored.py": "VALUE = 1\n",
            "app/m.py": "import sys\nsys.path.insert(0, '../vendor')\nimport vendored\n",
        },
    )

    names = jedi.Script(path=str(tmp_path / "app/m.py")).goto(3, 8, follow_imports=True)

    assert [n.module_name for n in names] == ["vendored"]


@pytest.mark.usefixtures("windows_rules")
class TestEditableFinderTargets:
    """An editable install's finder module names its targets (#1045): none is looked up.

    A target's root is found lexically (``_root_for``; ``package_kind`` reads a
    ``.py`` path's name only), and every root then goes through
    ``_checked_dirs``, the one lookup of ``.pth`` and finder paths alike, which
    checks it as written first.
    """

    @pytest.mark.parametrize(
        ("pth", "module"),
        [
            (
                "import __editable___evil_0_1_finder; __editable___evil_0_1_finder.install()",
                f"MAPPING: dict[str, str] = {{'evil': '//{HOST}/share/evil/__init__.py'}}\n"
                f"NAMESPACES: dict[str, list[str]] = {{'ns': ['//{HOST}/share/ns']}}\n",
            ),
            (
                "import _editable_impl_evil",
                "from editables.redirector import RedirectingFinder as F\nF.install()\n"
                f"F.map_module('evil', '//{HOST}/share/evil.py')\n",
            ),
        ],
        ids=["setuptools", "editables"],
    )
    def test_a_network_target_is_never_looked_up(
        self, tmp_path: Path, touched: list[str], pth: str, module: str
    ) -> None:
        from pyeye.environment import site_paths

        site = tmp_path / ".venv/Lib/site-packages"
        site.mkdir(parents=True)
        finder = pth.split(";")[0].split()[1]
        (site / "evil.pth").write_text(pth, encoding="utf-8")
        (site / f"{finder}.py").write_text(module, encoding="utf-8")

        paths = site_paths(tmp_path / ".venv")

        assert touched == []
        assert not any(HOST in p for p in paths)


class TestFollowUps:
    """#1056: the low items from #1053's final review."""

    def test_posix_never_expands_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """On POSIX nothing is refused, so ``~user`` isn't expanded (no pointless pwd lookup)."""
        import os

        from pyeye.path_utils import repo_path_refusal

        monkeypatch.setattr(path_utils, "_ON_WINDOWS", False)

        def boom(_: str) -> str:
            raise AssertionError("expanded on POSIX")

        monkeypatch.setattr(os.path, "expanduser", boom)

        assert repo_path_refusal("~someone/lib") is None
        assert repo_path_refusal("~/lib") is None

    def test_the_filter_installs_even_when_an_earlier_patch_step_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import jedi.inference.sys_path as jedi_sys_path

        from pyeye import _parso_cache

        unwrapped = jedi_sys_path.check_sys_path_modifications.__wrapped__
        monkeypatch.setattr(jedi_sys_path, "check_sys_path_modifications", unwrapped)

        def broken(*_: Any) -> None:
            raise RuntimeError("a Jedi upgrade moved this")

        monkeypatch.setattr(_parso_cache, "_install_own_tree_guard", broken)

        with pytest.raises(RuntimeError, match="moved this"):
            _parso_cache._install_recovery()

        assert _parso_cache._is_marked(jedi_sys_path.check_sys_path_modifications)

    def test_a_failing_filter_install_warns_and_recovery_still_completes(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        from pyeye import _parso_cache

        def broken() -> None:
            raise RuntimeError("filter install failed")

        monkeypatch.setattr(_parso_cache, "_install_sys_path_filter", broken)

        with caplog.at_level("WARNING"):
            _parso_cache._install_recovery()  # must not raise

        assert "filter install failed" in caplog.text
        assert "NOT filtered" in caplog.text
