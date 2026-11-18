"""The security facts SECURITY.md binds (#830, design C15)."""

from __future__ import annotations

import ast
import os
from pathlib import Path
from textwrap import dedent

import pytest

import pyeye
from pyeye import _jedi_project
from pyeye.constants import CONFIG_FILE
from pyeye.docs_facts import registry
from pyeye.docs_facts.extractors import security
from pyeye.docs_facts.facts import ExtractionError
from pyeye.validation import PathValidator, ValidationError

ROOT = Path(__file__).resolve().parent.parent


def _sites(source: str, module: str = "pyeye.m") -> tuple[set[str], set[str]]:
    tree = ast.parse(dedent(source))
    found = security._Sites(module, tree)
    found.visit(tree)
    return found.process, found.write


class TestProcessSites:
    @pytest.mark.parametrize(
        "source",
        [
            "import subprocess\ndef f():\n    subprocess.run(['git'])\n",
            "import subprocess as sp\ndef f():\n    sp.Popen('x')\n",
            "from subprocess import check_output\ndef f():\n    check_output(['x'])\n",
            "import os\ndef f():\n    os.system('x')\n",
            "import os\ndef f():\n    os.execvp('x', [])\n",
            "import asyncio\nasync def f():\n    await asyncio.create_subprocess_exec('x')\n",
            "import multiprocessing\ndef f():\n    multiprocessing.Process(target=None)\n",
            "import concurrent.futures\ndef f():\n    concurrent.futures.ProcessPoolExecutor()\n",
        ],
    )
    def test_each_way_of_starting_a_process_is_found(self, source: str) -> None:
        assert _sites(source)[0] == {"pyeye.m:f"}

    def test_lookalikes_are_not(self) -> None:
        source = """
            import os, threading
            class C:
                def run(self):
                    threading.Thread(target=None).start()
                    os.path.join('a', 'b')
                    self.system('x')
        """
        assert _sites(source)[0] == set()


class TestNetworkImports:
    def test_networking_imports_are_found_anywhere(self) -> None:
        source = """
            import socket
            def f():
                from urllib.request import urlopen
                import http.client
            import os
        """
        tree = ast.parse(dedent(source))
        found = security._Sites("pyeye.m", tree)
        found.visit(tree)
        assert found.network == {
            "pyeye.m:<module> imports socket",
            "pyeye.m:f imports urllib.request",
            "pyeye.m:f imports http.client",
        }


class TestWriteSites:
    @pytest.mark.parametrize(
        "source",
        [
            "def f(p):\n    open(p, 'w')\n",
            "def f(p):\n    open(p, mode='a')\n",
            "def f(p, m):\n    open(p, m)\n",  # a computed mode might write
            "def f(p):\n    p.open('x')\n",
            "def f(p):\n    p.write_text('x')\n",
            "def f(p):\n    p.mkdir(parents=True)\n",
            "import os\ndef f(p):\n    os.makedirs(p)\n",
            "import shutil\ndef f(a, b):\n    shutil.move(a, b)\n",
            "import logging\ndef f(p):\n    logging.FileHandler(p)\n",
        ],
    )
    def test_each_way_of_writing_is_found(self, source: str) -> None:
        assert _sites(source)[1] == {"pyeye.m:f"}

    def test_reads_are_not_writes(self) -> None:
        source = "def f(p):\n    open(p)\n    open(p, 'rb')\n    p.read_text()\n    p.open()\n"
        assert _sites(source)[1] == set()

    def test_a_site_is_named_by_its_scope_not_its_line(self) -> None:
        source = """
            class C:
                def save(self, p):
                    p.write_text('x')
            open('log', 'a')
        """
        assert _sites(source)[1] == {"pyeye.m:C.save", "pyeye.m:<module>"}


def _package(tmp_path: Path, files: dict[str, str]) -> dict[str, tuple[str, ast.Module]]:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(text), encoding="utf-8")
    return security._modules(tmp_path)


class TestServerModules:
    def test_the_closure_follows_relative_absolute_and_local_imports(self, tmp_path: Path) -> None:
        modules = _package(
            tmp_path,
            {
                "__init__.py": "",
                "mcp/__init__.py": "",
                "mcp/__main__.py": "from .server import x\n",
                "mcp/server.py": "def f():\n    from ..lazy import y\nimport pyeye.direct\n",
                "lazy.py": "from . import sub\n",
                "sub.py": "",
                "direct.py": "",
                "tooling.py": "import subprocess\n",
            },
        )

        assert security.server_modules(modules) == {
            "pyeye",
            "pyeye.mcp",
            "pyeye.mcp.__main__",
            "pyeye.mcp.server",
            "pyeye.lazy",
            "pyeye.sub",
            "pyeye.direct",
        }

    def test_a_missing_entry_point_fails_loudly(self, tmp_path: Path) -> None:
        with pytest.raises(ExtractionError, match="entry point"):
            security.server_modules(_package(tmp_path, {"__init__.py": ""}))

    def test_repo_tooling_is_outside_and_its_subprocess_would_be_found(self) -> None:
        """docs_facts.changed runs git; it's excluded because the server never imports it."""
        modules = security._modules(Path(pyeye.__file__).parent)
        server = security.server_modules(modules)

        assert "pyeye.docs_facts.changed" not in server
        assert {"pyeye.mcp.server", "pyeye.validation", "pyeye._jedi_project"} <= server
        found = security._Sites("pyeye.docs_facts.changed", modules["pyeye.docs_facts.changed"][1])
        found.visit(modules["pyeye.docs_facts.changed"][1])
        assert found.process == {"pyeye.docs_facts.changed:base_snapshot"}


class TestFacts:
    @pytest.fixture(scope="class")
    def facts(self) -> dict[str, object]:
        return {f.id: f for f in security.extract(ROOT)}

    def test_the_server_starts_no_process(self, facts: dict[str, object]) -> None:
        assert facts["security.subprocesses"].value == []  # type: ignore[attr-defined]
        assert facts["security.subprocesses"].markdown == "none"  # type: ignore[attr-defined]

    def test_the_server_imports_no_networking_module(self, facts: dict[str, object]) -> None:
        assert facts["security.network_imports"].value == []  # type: ignore[attr-defined]

    def test_no_usage_metrics_are_written(self, facts: dict[str, object]) -> None:
        """#943: the unified metrics store, and its facts, are gone."""
        assert "security.metrics_inputs" not in facts
        assert "security.writes.metrics" not in facts

    def test_the_known_writers_are_listed(self, facts: dict[str, object]) -> None:
        sites = facts["security.write_sites"].value  # type: ignore[attr-defined]
        assert "pyeye.config:ProjectConfig.save_config" in sites
        assert "pyeye.mcp.__main__:_configure_logging" in sites
        assert not any(s.startswith("pyeye.unified_metrics:") for s in sites)  # #943
        assert sites == sorted(sites)

    def test_the_paths_come_from_the_constants(self, facts: dict[str, object]) -> None:
        assert facts["security.writes.config"].value == {  # type: ignore[attr-defined]
            "path": f"<project_path>/{CONFIG_FILE}"
        }

    def test_path_checks_match_what_validate_path_rejects(self, facts: dict[str, object]) -> None:
        rejected = facts["security.path_checks.rejected"].value  # type: ignore[attr-defined]
        for sequence, described in PathValidator.REJECTED_SEQUENCES:
            assert described in rejected
            with pytest.raises(ValidationError, match=described):
                PathValidator.validate_path(f"a{sequence}b")
        assert "security.path_checks.components" not in facts  # retired with the check (#939)
        targets = facts["security.path_checks.targets"].value  # type: ignore[attr-defined]
        assert targets == list(PathValidator.RESTRICTED_TARGETS)

    @pytest.mark.skipif(os.name == "nt", reason="the deny-list names POSIX system directories")
    def test_a_climb_to_a_restricted_target_is_rejected(self) -> None:
        """A relative path that climbs to /etc has no "/etc/" in its spelling, so only
        the target check (on its anchored forms) can stop it."""
        with pytest.raises(ValidationError, match="restricted location"):
            PathValidator.validate_path("../" * 40 + "etc", anchor_root=ROOT)

    def test_the_checked_forms_come_from_check_forms(self, facts: dict[str, object]) -> None:
        forms = facts["security.path_checks.forms"].value  # type: ignore[attr-defined]
        assert "lexical" in forms and "resolved" in forms
        assert len(PathValidator.check_forms(Path("/a/../b"))[1]) >= 1

    def test_a_changed_check_forms_docstring_fails_loudly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(PathValidator.check_forms, "__doc__", "Checks things.", raising=False)
        with pytest.raises(ExtractionError, match="check_forms"):
            list(security._path_checks())

    def test_jedi_unsafe_extensions_is_what_make_project_passes(
        self, facts: dict[str, object], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        passed: dict[str, object] = {}
        monkeypatch.setattr(_jedi_project.jedi, "Project", lambda **kw: passed.update(kw))
        _jedi_project.make_project(ROOT)

        assert passed["load_unsafe_extensions"] is False
        assert facts["security.jedi_unsafe_extensions"].value is False  # type: ignore[attr-defined]
        assert facts["security.jedi_unsafe_extensions"].markdown == "off"  # type: ignore[attr-defined]

    def test_the_family_is_registered(self) -> None:
        assert "security" in {p for e in registry.EXTRACTORS for p in e.prefixes}
