"""Plugin detection is cheap first, bounded, and off the startup path (#1143).

Before #1143, ``PydanticPlugin.detect()`` walked the whole tree for an import
before it looked at the declared dependencies, and ``main()`` ran it before the
stdio loop started: on a large tree (``$HOME``, a monorepo) the server served
nothing, and noticed no closed stdin, for over a minute. Now:

- Pydantic and Flask read the declared dependencies first (pyproject, every
  requirements file, Pipfile, uv.lock / poetry.lock), with no walk;
- the fallback import scan is bounded, and stopping at the bound reports
  ``not_determined``, never ``not_detected``;
- the entry point serves while detection runs on a thread, then registers the
  detected plugins' tools and announces them with a tools-changed event.
"""

from __future__ import annotations

import importlib
import threading
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import types
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

from pyeye.mcp import list_changed
from pyeye.mcp.__main__ import serve_detecting_plugins
from pyeye.plugins import detection
from pyeye.plugins.flask import FlaskPlugin
from pyeye.plugins.pydantic import PydanticPlugin

server = importlib.import_module("pyeye.mcp.server")

PLUGINS = {"pydantic": PydanticPlugin, "flask": FlaskPlugin}


@pytest.fixture
def no_walk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any tree walk the detection module makes."""

    def walk(_root: Path) -> Any:
        raise AssertionError("detection walked the tree")

    monkeypatch.setattr(detection, "filtered_walk", walk)


def _project(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "proj"
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    # Plenty of source with no framework import, so an import scan finds nothing.
    for i in range(3):
        (root / "pkg" / f"m{i}.py").parent.mkdir(parents=True, exist_ok=True)
        (root / "pkg" / f"m{i}.py").write_text("X = 1\n", encoding="utf-8")
    return root


def _declarations(framework: str) -> list[tuple[str, dict[str, str]]]:
    """Every manifest form that declares *framework*, as ``(id, files)``."""
    f = framework
    return [
        ("pep621", {"pyproject.toml": f'[project]\nname = "x"\ndependencies = ["{f}>=1"]\n'}),
        (
            "optional",
            {
                "pyproject.toml": f'[project]\nname = "x"\n[project.optional-dependencies]\nweb = ["{f}"]\n'
            },
        ),
        ("pep735", {"pyproject.toml": f'[dependency-groups]\ndev = ["{f}"]\n'}),
        ("uv-dev", {"pyproject.toml": f'[tool.uv]\ndev-dependencies = ["{f}"]\n'}),
        ("poetry", {"pyproject.toml": f'[tool.poetry.dependencies]\n{f} = "^2"\n'}),
        ("poetry-group", {"pyproject.toml": f'[tool.poetry.group.dev.dependencies]\n{f} = "*"\n'}),
        ("requirements", {"requirements.txt": f"{f.capitalize()}==2.0  # pinned\n"}),
        ("requirements-dev", {"requirements-dev.txt": f"{f}\n"}),
        ("requirements-dir", {"requirements/base.txt": f"{f}>=1\n"}),
        ("pipfile", {"Pipfile": f'[packages]\n{f} = "*"\n'}),
        ("uv.lock", {"uv.lock": f'version = 1\n[[package]]\nname = "{f}"\nversion = "2.0"\n'}),
        ("poetry.lock", {"poetry.lock": f'[[package]]\nname = "{f}"\nversion = "2.0"\n'}),
        ("extension", {"requirements.txt": f"{f}-extra-thing\n"}),
    ]


class TestDeclaredDependenciesComeFirst:
    @pytest.mark.parametrize("framework", sorted(PLUGINS))
    @pytest.mark.parametrize("form", range(13))
    @pytest.mark.usefixtures("no_walk")
    def test_a_declared_framework_is_detected_without_a_walk(
        self, tmp_path: Path, framework: str, form: int
    ) -> None:
        _, files = _declarations(framework)[form]
        root = _project(tmp_path, files)

        plugin = PLUGINS[framework](root.as_posix())
        assert plugin.detection() == "detected"
        assert plugin.detect() is True

    def test_every_form_is_tested(self) -> None:
        assert len(_declarations("x")) == 13

    @pytest.mark.parametrize(
        "text",
        [
            "not-pydantic\n",  # another distribution
            "# pydantic\n",  # a comment
            "-r pydantic.txt\n",  # an option line
            "pydanticx\n",  # a longer name
        ],
    )
    def test_only_the_name_counts(self, tmp_path: Path, text: str) -> None:
        root = _project(tmp_path, {"requirements.txt": text})

        assert "pydantic" not in detection.declared_dependencies(root)
        assert detection.declares(root, "pydantic") is False

    def test_names_are_normalized(self, tmp_path: Path) -> None:
        root = _project(tmp_path, {"requirements.txt": "Flask_Login>=1\nzope.interface\n"})

        assert {"flask-login", "zope-interface"} <= detection.declared_dependencies(root)

    def test_an_unparseable_manifest_is_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        root = _project(
            tmp_path, {"pyproject.toml": "[project\n", "requirements.txt": "pydantic\n"}
        )

        with caplog.at_level("WARNING"):
            assert detection.declares(root, "pydantic") is True
        assert "pyproject.toml" in caplog.text


class TestTheFallbackScanIsBounded:
    @pytest.fixture
    def big(self, tmp_path: Path) -> Path:
        root = tmp_path / "big"
        for d in range(5):
            for f in range(10):
                path = root / f"d{d}" / f"f{f}.py"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("X = 1\n", encoding="utf-8")
        return root

    def _scan(self, root: Path, limit: int) -> str:
        return detection.scan_for_imports(
            root, ("import pydantic",), lambda p: p.read_text(), limit=limit
        )

    def test_a_scan_stopped_at_the_bound_is_not_determined(self, big: Path) -> None:
        assert self._scan(big, limit=10) == "not_determined"

    def test_a_complete_scan_with_no_import_is_not_detected(self, big: Path) -> None:
        assert self._scan(big, limit=10_000) == "not_detected"

    def test_a_tree_that_ends_at_the_bound_was_scanned(self, big: Path) -> None:
        """The bound is checked on entering a directory, so a fully listed tree is decided."""
        total = 5 + 5 * 10  # five directories, fifty files
        assert self._scan(big, limit=total) == "not_detected"

    def test_an_import_within_the_bound_is_detected(self, big: Path) -> None:
        (big / "d0" / "f0.py").write_text("import pydantic\n", encoding="utf-8")

        assert self._scan(big, limit=10_000) == "detected"

    def test_a_large_file_is_not_read(self, big: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (big / "d0" / "f0.py").write_text("import pydantic\n", encoding="utf-8")
        monkeypatch.setattr(detection, "SCAN_MAX_FILE_BYTES", 4)

        assert self._scan(big, limit=10_000) == "not_detected"

    @pytest.mark.parametrize("framework", sorted(PLUGINS))
    def test_the_plugins_use_the_bound(
        self, big: Path, monkeypatch: pytest.MonkeyPatch, framework: str
    ) -> None:
        monkeypatch.setattr(detection, "SCAN_ENTRY_LIMIT", 10)
        plugin = PLUGINS[framework](big.as_posix())

        assert plugin.detection() == "not_determined"
        assert plugin.detect() is False

    @pytest.mark.parametrize("framework", sorted(PLUGINS))
    def test_an_import_is_still_found_without_a_declaration(
        self, tmp_path: Path, framework: str
    ) -> None:
        root = _project(tmp_path, {"pkg/deep/models.py": f"from {framework} import X\n"})

        assert PLUGINS[framework](root.as_posix()).detection() == "detected"


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch) -> MCPServer:
    """A fresh server for plugin registration, with the plugin registry saved and restored."""
    fresh = MCPServer("test-detection-startup")
    monkeypatch.setattr(server, "mcp", fresh)
    saved = list(server._plugins), set(server._registered_plugin_tools)
    saved_detection = dict(server._plugin_detection)
    yield fresh
    server._plugins[:] = saved[0]
    server._registered_plugin_tools.clear()
    server._registered_plugin_tools.update(saved[1])
    server._plugin_detection.clear()
    server._plugin_detection.update(saved_detection)


class TestTheServerRecordsTheOutcome:
    def test_not_determined_is_recorded_and_lists_no_tools(
        self, isolated: MCPServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _project(tmp_path, {})
        monkeypatch.setattr(
            PydanticPlugin, "detection", lambda _self: "not_determined", raising=True
        )

        server.initialize_plugins(root.as_posix())

        assert server.plugin_detection()["Pydantic"] == "not_determined"
        assert server.plugin_detection()["Flask"] == "not_detected"
        tools = {t.name for t in anyio.run(isolated.list_tools)}
        assert "find_pydantic_models" not in tools

    def test_pending_until_detection_is_committed(
        self, isolated: MCPServer, tmp_path: Path
    ) -> None:
        root = _project(tmp_path, {"requirements.txt": "flask\n"})

        server.prepare_plugins(root.as_posix())
        assert set(server.plugin_detection().values()) == {"pending"}

        names = server.commit_plugins(root.as_posix(), server.detect_plugins(root.as_posix()))

        assert names == ["Flask"]
        assert server.plugin_detection()["Flask"] == "detected"
        assert "find_flask_routes" in {t.name for t in anyio.run(isolated.list_tools)}

    @pytest.mark.usefixtures("isolated")
    def test_a_second_commit_of_the_same_framework_activates_it_once(self, tmp_path: Path) -> None:
        """Startup's background commit and a configure_packages re-detection can both find it."""
        root = _project(tmp_path, {"requirements.txt": "flask\n"})
        server.prepare_plugins(root.as_posix())
        detected = server.detect_plugins(root.as_posix())

        assert server.commit_plugins(root.as_posix(), detected) == ["Flask"]
        assert server.commit_plugins(root.as_posix(), detected) == []
        assert [p.name() for p in server._plugins] == ["Flask"]

    @pytest.mark.usefixtures("isolated")
    def test_a_failing_detector_is_not_determined(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(_self: Any) -> str:
            raise RuntimeError("detector bug")

        monkeypatch.setattr(FlaskPlugin, "detection", boom)
        root = _project(tmp_path, {})

        server.initialize_plugins(root.as_posix())

        assert server.plugin_detection()["Flask"] == "not_determined"


class _Recorder:
    def __init__(self) -> None:
        self.changed = 0

    async def __call__(self, message: Any) -> None:
        if isinstance(message, types.ToolListChangedNotification):
            self.changed += 1


class TestStartupDoesNotWaitForDetection:
    @pytest.mark.asyncio
    async def test_the_server_answers_while_detection_runs_then_announces(
        self, isolated: MCPServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _project(tmp_path, {"requirements.txt": "flask\n"})
        server.prepare_plugins(root.as_posix())
        release = threading.Event()
        real = server.detect_plugins

        def slow(project_path: str, *args: Any) -> Any:
            assert release.wait(30), "the test never released detection"
            return real(project_path, *args)

        monkeypatch.setattr(server, "detect_plugins", slow)
        recorder = _Recorder()
        seen: dict[str, Any] = {}

        async def transport(srv: MCPServer) -> None:
            async with Client(srv, mode="legacy", message_handler=recorder) as client:
                # Answered while detection is blocked: serving didn't wait for it.
                seen["before"] = {t.name for t in (await client.list_tools()).tools}
                seen["pending"] = server.plugin_detection()["Flask"]
                release.set()
                with anyio.fail_after(30):
                    while recorder.changed == 0:
                        await anyio.sleep(0.02)
                seen["after"] = {t.name for t in (await client.list_tools()).tools}

        with anyio.fail_after(60):
            await serve_detecting_plugins(isolated, root.as_posix(), transport)

        assert seen["pending"] == "pending"
        assert "find_flask_routes" not in seen["before"]
        assert "find_flask_routes" in seen["after"]
        assert recorder.changed == 1
        assert server.plugin_detection()["Flask"] == "detected"

    @pytest.mark.asyncio
    async def test_serving_ends_without_waiting_for_detection(
        self, isolated: MCPServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A client that leaves mid-detection (EOF) ends the server; detection is abandoned."""
        root = _project(tmp_path, {})
        server.prepare_plugins(root.as_posix())
        never = threading.Event()
        monkeypatch.setattr(server, "detect_plugins", lambda *_a: never.wait(30) and [])

        async def transport(_srv: MCPServer) -> None:
            return  # stdin closed at once

        try:
            with anyio.fail_after(10):
                await serve_detecting_plugins(isolated, root.as_posix(), transport)
        finally:
            never.set()

    @pytest.mark.asyncio
    async def test_nothing_detected_announces_nothing(
        self, isolated: MCPServer, tmp_path: Path
    ) -> None:
        root = _project(tmp_path, {})
        server.prepare_plugins(root.as_posix())
        recorder = _Recorder()

        async def transport(srv: MCPServer) -> None:
            async with Client(srv, mode="legacy", message_handler=recorder) as client:
                with anyio.fail_after(30):
                    while server.plugin_detection()["Flask"] == "pending":
                        await client.list_tools()
                        await anyio.sleep(0.02)
                await anyio.sleep(0.05)

        await serve_detecting_plugins(isolated, root.as_posix(), transport)

        assert recorder.changed == 0


class TestTheNotifier:
    @pytest.mark.asyncio
    async def test_an_announcement_reaches_a_connected_handshake_client(self) -> None:
        srv = MCPServer("notifier")
        notifier = list_changed.ToolsChangedNotifier(srv).install()
        recorder = _Recorder()
        async with Client(srv, mode="legacy", message_handler=recorder) as client:
            await client.list_tools()
            await notifier.announce()
            await anyio.sleep(0.05)

        assert recorder.changed == 1

    @pytest.mark.asyncio
    async def test_an_announcement_before_the_handshake_waits_for_the_client(self) -> None:
        srv = MCPServer("notifier")
        notifier = list_changed.ToolsChangedNotifier(srv).install()
        await notifier.announce()  # nobody connected yet
        recorder = _Recorder()
        async with Client(srv, mode="legacy", message_handler=recorder) as client:
            await client.list_tools()
            await client.list_tools()
            await anyio.sleep(0.05)

        assert recorder.changed == 1  # sent once, on the client's first message

    @pytest.mark.asyncio
    async def test_a_modern_client_gets_it_on_its_listen_stream(self) -> None:
        srv = MCPServer("notifier")
        notifier = list_changed.ToolsChangedNotifier(srv).install()
        events: list[Any] = []
        async with (
            Client(srv, mode=MODERN_PROTOCOL_VERSIONS[-1]) as client,
            client.listen(tools_list_changed=True) as subscription,
        ):
            await client.list_tools()
            await notifier.announce()
            with anyio.move_on_after(2):
                async for event in subscription:
                    events.append(event)
                    break

        assert [type(e).__name__ for e in events] == ["ToolsListChanged"]

    @pytest.mark.asyncio
    async def test_a_failed_send_is_logged_not_raised(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        notifier = list_changed.ToolsChangedNotifier(MCPServer("notifier"))

        class Broken:
            async def send_tool_list_changed(self) -> None:
                raise RuntimeError("gone")

        notifier._session = Broken()
        with caplog.at_level("WARNING"):
            await notifier.announce()

        assert "Could not announce new tools" in caplog.text
