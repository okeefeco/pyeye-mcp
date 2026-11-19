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

import json
import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from pyeye import (
    project_manager as project_manager_module,
    validation,
)
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline
from pyeye.mcp.operations.resolve import resolve, resolve_at
from pyeye.mcp.operations.trace import trace
from pyeye.project_manager import ProjectManager

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
def isolated_manager(monkeypatch: pytest.MonkeyPatch) -> Iterator[ProjectManager]:
    manager = ProjectManager(max_projects=10)
    monkeypatch.setattr(project_manager_module, "_project_manager", manager)
    yield manager
    manager.cleanup_all()


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
        # Reported by the class's own spelling, never a name from the restricted file.
        assert bases["unresolved_superclasses"] == ["Base"]
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


@pytest.fixture
def inherited(tmp_path: Path, restricted: Path) -> Path:
    """The #1003 review's setup: project symbols that inherit or alias restricted ones."""
    pkg = restricted / "pkg"
    (pkg / "__init__.py").write_text("from ._hidden_impl import thing\n", encoding="utf-8")
    (pkg / "_hidden_impl.py").write_text("def thing():\n    pass\n", encoding="utf-8")
    (pkg / "keys.py").write_text(
        "class Base:\n    def __init__(self, marker='LEAKMARK'):\n        pass\n\n\n"
        "def leak(secret_arg):\n    return 1\n",
        encoding="utf-8",
    )
    project = _project(
        tmp_path,
        "from etcmod2.keys import Base, leak\nfrom etcmod2 import thing\n\n\n"
        "class Child(Base):\n    pass\n\n\nalias = leak\n",
    )
    (project / "etcmod2").symlink_to(pkg, target_is_directory=True)
    return project


class TestThroughProjectSymbols:
    """Content inferred from a restricted definition through a PROJECT symbol (#1003 review)."""

    @pytest.mark.asyncio
    async def test_an_inherited_signature_is_not_shown(self, inherited: Path) -> None:
        analyzer = JediAnalyzer(str(inherited))

        node = await inspect("app.Child", analyzer)

        assert node["found"] is True
        assert "LEAKMARK" not in json.dumps(node) and "signature" not in node, node

    @pytest.mark.asyncio
    async def test_stub_signatures_in_outline_members_and_trace(self, inherited: Path) -> None:
        analyzer = JediAnalyzer(str(inherited))

        results = (
            await outline("app", analyzer),
            await expand("app", "members", analyzer),
            await trace("app", ["members"], analyzer, max_depth=1),
        )
        for result in results:
            text = json.dumps(result)
            assert "LEAKMARK" not in text and "secret_arg" not in text, text

    @pytest.mark.asyncio
    async def test_a_restricted_base_is_unresolved_everywhere(self, inherited: Path) -> None:
        """inspect's field and count agree with the edge, by the class's own spelling."""
        analyzer = JediAnalyzer(str(inherited))

        node = await inspect("app.Child", analyzer)
        edge = await expand("app.Child", "superclasses", analyzer)

        assert node["superclasses"] == ["Base"], node
        assert node["edge_counts"].get("superclasses", 0) == len(edge["stubs"]) == 0
        assert edge["unresolved_superclasses"] == ["Base"]

    @pytest.mark.asyncio
    async def test_loss_fields_use_the_importers_spelling(self, inherited: Path) -> None:
        """A canonical handle would name the restricted file's internals (_hidden_impl)."""
        analyzer = JediAnalyzer(str(inherited))

        edge = await expand("app", "imports", analyzer)

        assert "_hidden_impl" not in json.dumps(edge), edge
        assert "etcmod2.thing" in edge["unresolved_imports"]

    @pytest.mark.asyncio
    async def test_a_restricted_copy_is_no_shadow_candidate(self, inherited: Path) -> None:
        (inherited / "src" / "shadowpkg").mkdir(parents=True)
        (inherited / "src" / "shadowpkg" / "__init__.py").write_text("", encoding="utf-8")
        (inherited / "shadowpkg").symlink_to(inherited / "etcmod2", target_is_directory=True)
        analyzer = JediAnalyzer(str(inherited))

        result = await resolve("shadowpkg", analyzer)

        assert result["found"] is True and not result.get("ambiguous"), result
        assert result["location"]["file"].endswith("src/shadowpkg/__init__.py")


@pytest.mark.usefixtures("isolated_manager")
@pytest.mark.asyncio
async def test_pydantic_inheritance_doesnt_read_a_restricted_ancestor(
    tmp_path: Path, restricted: Path
) -> None:
    """trace_model_inheritance reported a restricted ancestor and its field defaults."""
    from pyeye.plugins.pydantic import PydanticPlugin

    (restricted / "pkg" / "models.py").write_text(
        "from pydantic import BaseModel\n\n\n"
        "class SecretModel(BaseModel):\n    db_note: str = 'LEAKMARK'\n",
        encoding="utf-8",
    )
    project = _project(tmp_path, "")
    (project / "models_app.py").write_text(
        "from pydantic import BaseModel\n\nfrom etcmod2.models import SecretModel\n\n\n"
        "class Child(SecretModel, BaseModel):\n    own: int = 1\n",
        encoding="utf-8",
    )
    (project / "etcmod2").symlink_to(restricted / "pkg", target_is_directory=True)
    # The test's own environment, so pydantic resolves as it would in a real venv.
    (project / ".pyeye.json").write_text(
        json.dumps({"environment": Path(sys.prefix).as_posix()}), encoding="utf-8"
    )

    result = await PydanticPlugin(str(project)).trace_model_inheritance("Child", scope="all")

    text = json.dumps(result)
    assert "LEAKMARK" not in text and "db_note" not in text, text
    assert "fields_inherited" not in result or not result["fields_inherited"], result


@pytest.mark.asyncio
async def test_an_annotation_head_in_a_restricted_dir_gets_no_handle(
    tmp_path: Path, restricted: Path
) -> None:
    """A TypeRef handle would name the restricted file's internals (``_hidden``).

    Every head form: a bare name, an attribute (``K.Base``), a return type, and
    annotated module and class attributes.
    """
    pkg = restricted / "pkg"
    (pkg / "__init__.py").write_text("from ._hidden import Thing\n", encoding="utf-8")
    (pkg / "_hidden.py").write_text("class Thing:\n    pass\n", encoding="utf-8")
    (pkg / "keys.py").write_text("class Base:\n    pass\n", encoding="utf-8")
    project = _project(
        tmp_path,
        "import etcmod2.keys as K\nfrom etcmod2 import Thing\nfrom etcmod2.keys import Base\n\n\n"
        "def annotated(x: Thing, r: K.Base) -> Thing:\n    return x\n\n\n"
        "attr: Base = None\n\n\n"
        "class Holder:\n    field: Base = None\n",
    )
    (project / "etcmod2").symlink_to(pkg, target_is_directory=True)
    analyzer = JediAnalyzer(str(project))

    nodes = [
        await inspect(handle, analyzer)
        for handle in ("app.annotated", "app.attr", "app.Holder", "app.Holder.field")
    ]

    assert all(node["found"] for node in nodes), nodes
    text = json.dumps(nodes)
    assert "_hidden" not in text and "etcmod2.keys.Base" not in text, text
    assert "handle" not in nodes[0]["return_type"], nodes[0]["return_type"]


def test_a_symlink_loop_fails_closed_on_every_python(tmp_path: Path) -> None:
    """Python 3.13 stopped raising on a loop in a non-strict resolve (#1003 review)."""
    from pyeye.resolver import restricted_path

    loop = tmp_path / "loop"
    loop.symlink_to(loop)

    assert restricted_path(loop / "x.py") is True
    assert restricted_path(loop) is True


def test_a_missing_file_isnt_refused_but_a_dangling_link_into_one_is(
    tmp_path: Path, restricted: Path
) -> None:
    from pyeye.resolver import restricted_path

    assert restricted_path(tmp_path / "not-yet.py") is False
    dangling = tmp_path / "dangling"
    dangling.symlink_to(restricted / "gone.py")
    assert restricted_path(dangling) is True
