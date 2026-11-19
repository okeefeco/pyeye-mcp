"""No result is returned from a file that RESOLVES into a restricted directory (#999).

The input path checks (#856, #909, #939) and the pruned walks don't cover
Jedi's own import lookup. A symlink inside the project, or inside the project
venv's site-packages (#993), pointing at ``/etc`` or a credential store was
followed, and pyeye returned the target's symbols and locations. These tests
pin that such a hit is refused with an honest reason, through every tool,
while a symlink to an allowed directory, and a symlinked project root, keep
working.

POSIX only: the deny-list is POSIX, and the symlinks need no privileges there.
Most tests stand a temporary directory in for the restricted one by patching
``validation._RESTRICTED_DIRS``, so they don't depend on what ``/etc`` holds.
One reads the real ``/etc`` when it has a ``.py`` to follow.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from pyeye import validation
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline
from pyeye.mcp.operations.resolve import resolve, resolve_at
from pyeye.mcp.operations.trace import trace

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the deny-list and symlinks are POSIX")

RESTRICTED = "restricted directory"


def _secret_package(directory: Path) -> Path:
    """A package with a module that would leak: a docstring and a symbol."""
    directory.mkdir(parents=True)
    (directory / "__init__.py").write_text("", encoding="utf-8")
    (directory / "keys.py").write_text('"""Secret."""\n\nTOKEN = "x"\n', encoding="utf-8")
    return directory


def _venv(project: Path) -> Path:
    site = project / ".venv" / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    (project / ".venv" / "pyvenv.cfg").write_text("version = 3.12.3\n", encoding="utf-8")
    return site


@pytest.fixture
def restricted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temporary directory the deny-list treats as restricted, like /etc."""
    secret = _secret_package(tmp_path / "secret" / "pkg").parent
    monkeypatch.setattr(validation, "_RESTRICTED_DIRS", (secret.resolve().as_posix(),))
    return secret


@pytest.fixture
def home_at(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[Path], None]]:
    def set_home(home: Path) -> None:
        monkeypatch.setattr(Path, "home", lambda: home)
        validation._credential_pattern.cache_clear()

    yield set_home
    monkeypatch.undo()
    validation._credential_pattern.cache_clear()


def _project(tmp_path: Path, importer: str) -> Path:
    project = tmp_path / "proj"
    project.mkdir(exist_ok=True)
    (project / "app.py").write_text(importer, encoding="utf-8")
    return project


async def _assert_refused(analyzer: JediAnalyzer, handle: str) -> None:
    for tool in (resolve, inspect, outline):
        result = await tool(handle, analyzer)
        assert result["found"] is False, (tool.__name__, result)
        assert result["reason"] == "unresolved", (tool.__name__, result)
        assert RESTRICTED in result["detail"], (tool.__name__, result)


async def _assert_not_emitted(analyzer: JediAnalyzer, handle: str) -> None:
    edge = await expand("app", "imports", analyzer)
    assert handle not in {s["handle"] for s in edge["stubs"]}
    assert any(handle in entry for entry in edge["unresolved_imports"]), edge
    graph = await trace("app", ["imports"], analyzer, max_depth=1)
    assert handle not in graph["nodes"]


class TestRefused:
    @pytest.mark.asyncio
    async def test_a_site_packages_symlink_into_a_restricted_dir(
        self, tmp_path: Path, restricted: Path
    ) -> None:
        project = _project(tmp_path, "import etcmod.keys\n")
        (_venv(project) / "etcmod").symlink_to(restricted / "pkg", target_is_directory=True)
        analyzer = JediAnalyzer(str(project))

        await _assert_refused(analyzer, "etcmod.keys")
        await _assert_refused(analyzer, "etcmod.keys.TOKEN")
        await _assert_not_emitted(analyzer, "etcmod.keys")

    @pytest.mark.asyncio
    async def test_a_project_symlink_into_a_restricted_dir(
        self, tmp_path: Path, restricted: Path
    ) -> None:
        project = _project(tmp_path, "import etcmod2.keys\n")
        (project / "etcmod2").symlink_to(restricted / "pkg", target_is_directory=True)
        analyzer = JediAnalyzer(str(project))

        await _assert_refused(analyzer, "etcmod2.keys")
        await _assert_refused(analyzer, "etcmod2")
        await _assert_not_emitted(analyzer, "etcmod2.keys")

    @pytest.mark.asyncio
    async def test_a_project_symlink_into_a_credential_store(
        self, tmp_path: Path, home_at: Callable[[Path], None]
    ) -> None:
        home = tmp_path / "home"
        _secret_package(home / ".ssh" / "pkg")
        home_at(home)
        project = _project(tmp_path, "import sshmod.keys\n")
        (project / "sshmod").symlink_to(home / ".ssh" / "pkg", target_is_directory=True)
        analyzer = JediAnalyzer(str(project))

        await _assert_refused(analyzer, "sshmod.keys")
        await _assert_not_emitted(analyzer, "sshmod.keys")

    @pytest.mark.asyncio
    async def test_resolve_at_on_the_import_is_refused(
        self, tmp_path: Path, restricted: Path
    ) -> None:
        project = _project(tmp_path, "import etcmod2.keys\n")
        (project / "etcmod2").symlink_to(restricted / "pkg", target_is_directory=True)
        analyzer = JediAnalyzer(str(project))

        result = await resolve_at(str(project / "app.py"), 1, 15, analyzer)

        assert result["found"] is False and RESTRICTED in result["detail"], result

    @pytest.mark.asyncio
    async def test_the_real_etc(self, tmp_path: Path) -> None:
        """The case #999 reported: a project symlink to /etc/python3.x."""
        targets = sorted(Path("/etc").glob("python3*/sitecustomize.py"))
        if not targets:
            pytest.skip("no /etc/python3*/sitecustomize.py on this machine")
        project = _project(tmp_path, "")
        (project / "etcmod2").symlink_to(targets[0].parent, target_is_directory=True)
        analyzer = JediAnalyzer(str(project))

        await _assert_refused(analyzer, "etcmod2.sitecustomize")


class TestKept:
    @pytest.mark.asyncio
    @pytest.mark.usefixtures("restricted")  # the deny-list is active; these targets are outside it
    async def test_a_symlink_into_an_allowed_dir_still_resolves(self, tmp_path: Path) -> None:
        shared = _secret_package(tmp_path / "shared" / "pkg")
        project = _project(tmp_path, "import libmod.keys\n")
        (_venv(project) / "libmod").symlink_to(shared, target_is_directory=True)
        (project / "linked").symlink_to(shared, target_is_directory=True)
        analyzer = JediAnalyzer(str(project))

        for handle in ("libmod.keys", "linked.keys"):
            result = await resolve(handle, analyzer)
            assert result["found"] is True, (handle, result)
        edge = await expand("app", "imports", analyzer)
        assert "libmod.keys" in {s["handle"] for s in edge["stubs"]}

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("restricted")  # the deny-list is active; these targets are outside it
    async def test_a_symlinked_project_root_still_works(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        _secret_package(real / "pkg")
        (tmp_path / "alias").symlink_to(real, target_is_directory=True)
        analyzer = JediAnalyzer(str(tmp_path / "alias"))

        result = await resolve("pkg.keys.TOKEN", analyzer)

        assert result["found"] is True and result["scope"] == "project", result


class TestOtherEdges:
    @pytest.mark.asyncio
    async def test_a_base_and_a_callee_in_a_restricted_dir_are_reported_as_losses(
        self, tmp_path: Path, restricted: Path
    ) -> None:
        (restricted / "pkg" / "keys.py").write_text(
            "class Base:\n    pass\n\n\ndef leak():\n    return 1\n", encoding="utf-8"
        )
        project = _project(
            tmp_path,
            "from etcmod2.keys import Base, leak\n\n\n"
            "class Child(Base):\n    pass\n\n\n"
            "def run():\n    return leak()\n",
        )
        (project / "etcmod2").symlink_to(restricted / "pkg", target_is_directory=True)
        analyzer = JediAnalyzer(str(project))

        bases = await expand("app.Child", "superclasses", analyzer)
        assert bases["stubs"] == []
        assert "etcmod2.keys.Base" in bases["unresolved_superclasses"]
        calls = await expand("app.run", "callees", analyzer)
        assert "etcmod2.keys.leak" not in {s["handle"] for s in calls["stubs"]}
        assert calls["unresolved_call_sites"] >= 1


def test_an_edge_without_a_loss_field_drops_with_a_warning(
    tmp_path: Path, restricted: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Defensive: no such edge reaches a restricted file today, but none may leak one."""
    from types import SimpleNamespace

    from pyeye.handle import Handle
    from pyeye.mcp.operations import expand as expand_module
    from pyeye.mcp.operations.edges import EdgeResult

    inside = SimpleNamespace(module_path=restricted / "pkg" / "keys.py")
    outside = SimpleNamespace(module_path=tmp_path / "ok.py")
    result = EdgeResult(adjacents=[(Handle("a.inside"), inside), (Handle("a.outside"), outside)])

    with caplog.at_level("WARNING"):
        kept = expand_module._without_restricted("members", result)

    assert [str(h) for h, _ in kept.adjacents] == ["a.outside"]
    assert "restricted directory" in caplog.text
