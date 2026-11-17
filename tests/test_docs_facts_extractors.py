"""The fact extractors (#824), checked against the live code they read.

Each test compares an extractor's output with the same thing read another way
(the SDK's tool list, ``inspect.signature``, the edge functions, a fresh
``PerformanceSettings``), so an extractor that silently matched nothing, or
misread its source, fails here.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from pyeye.docs_facts import registry
from pyeye.docs_facts.extractors import ci
from pyeye.docs_facts.facts import Bindable, Fact, View
from pyeye.docs_facts.registry import Extractor, build

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def facts() -> dict[str, Bindable]:
    return build(ROOT)


def _fact(facts: dict[str, Bindable], fact_id: str) -> Fact:
    item = facts[fact_id]
    assert isinstance(item, Fact), fact_id
    return item


def _members(facts: dict[str, Bindable], view_id: str) -> list[str]:
    item = facts[view_id]
    assert isinstance(item, View), view_id
    return list(item.members)


def _names(ids: list[str]) -> set[str]:
    return {i.split(".", 1)[1] for i in ids}


class TestMcpSurface:
    def test_core_tools_are_the_registered_ones(self, facts: dict[str, Bindable]) -> None:
        from pyeye.mcp.server import mcp

        registered = {t.name for t in asyncio.run(mcp.list_tools())}
        admin = _names(_members(facts, "tools.admin"))

        assert _names(_members(facts, "tools.core")) == registered - admin
        assert admin == {"get_performance_metrics", "get_connection_diagnostics"}

    def test_plugin_tools_are_the_declared_ones(self, facts: dict[str, Bindable]) -> None:
        from pyeye.mcp.server import _PLUGIN_CLASSES

        for plugin_class in _PLUGIN_CLASSES:
            plugin = plugin_class(ROOT.as_posix())
            ids = _members(facts, f"tools.plugin.{plugin.name().lower()}")

            assert _names(ids) == set(plugin.register_tools())
            for tool_id in ids:
                assert _fact(facts, tool_id).value["group"] == "plugin"

    def test_core_parameters_match_the_signatures(self, facts: dict[str, Bindable]) -> None:
        from pyeye.mcp import server

        for tool_id in _members(facts, "tools.core"):
            name = tool_id.split(".", 1)[1]
            signature = inspect.signature(getattr(server, name))
            params = _fact(facts, tool_id).value["params"]

            assert [p.rsplit(".", 1)[1] for p in params] == list(signature.parameters), name
            for param_id in params:
                param = signature.parameters[param_id.rsplit(".", 1)[1]]
                value = _fact(facts, param_id).value
                assert value["required"] == (param.default is inspect.Parameter.empty)
                if not value["required"]:
                    assert value["default"] == param.default, param_id

    def test_a_known_parameter(self, facts: dict[str, Bindable]) -> None:
        assert _fact(facts, "tool.trace.param.max_depth").value == {
            "type": "int",
            "required": False,
            "default": 3,
        }
        assert "| `max_depth` | `int` | `3` |" in facts["tool.trace.params"].markdown


class TestEdges:
    def test_statuses_follow_the_registry(self, facts: dict[str, Bindable]) -> None:
        from pyeye.mcp.operations import edges

        implemented = _names(_members(facts, "edges.implemented"))
        deferred = _names(_members(facts, "edges.deferred"))

        assert implemented == set(edges.EDGE_RESOLVERS)
        assert deferred and all(
            edges.edge_status(e) == edges.STATUS_DEFERRED_REFERENCE_BACKEND for e in deferred
        )
        assert facts["edges.implemented"].markdown.startswith("`members`, `callees`")

    def test_each_edge_has_its_ceiling(self, facts: dict[str, Bindable]) -> None:
        from pyeye.mcp.operations import edges

        for name in edges.EDGE_RESOLVERS:
            value = _fact(facts, f"edge.{name}").value
            assert value["ceiling"] == edges.EDGE_CEILINGS.get(name), name
            assert value["applies_to"] == sorted(edges.EDGE_APPLIES_TO[name])
        for ceiling, meaning in edges.CEILING_MEANINGS.items():
            assert _fact(facts, f"ceiling.{ceiling}").value == {"meaning": meaning}


class TestEnv:
    def test_defaults_match_a_fresh_settings_object(
        self, facts: dict[str, Bindable], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pyeye.settings import PerformanceSettings

        for fact_id in _members(facts, "env.all"):
            monkeypatch.delenv(fact_id.split(".", 1)[1], raising=False)
        fresh = vars(PerformanceSettings())
        loaded = {
            i: _fact(facts, i).value
            for i in _members(facts, "env.all")
            if _fact(facts, i).value["source"] == "pyeye/settings.py"
        }

        assert len(loaded) == len(fresh)
        assert sorted(v["default"] for v in loaded.values()) == sorted(fresh.values())

    def test_statuses(self, facts: dict[str, Bindable]) -> None:
        from pyeye.settings import DEPRECATED_ENV_VARS

        deprecated = _names(_members(facts, "env.deprecated"))
        assert deprecated == set(DEPRECATED_ENV_VARS)
        assert _fact(facts, "env.PYEYE_CACHE_TTL").value["status"] == "live"
        assert _fact(facts, "env.PYEYE_LOG_LEVEL").value == {
            "type": "str",
            "default": "INFO",
            "source": "pyeye/mcp/__main__.py",
            "status": "live",
        }


class TestCliAndCi:
    def test_entry_points(self, facts: dict[str, Bindable]) -> None:
        assert _fact(facts, "cli.script.pyeye-mcp").value == {"target": "pyeye.mcp.__main__:main"}
        assert _fact(facts, "cli.module.pyeye.mcp").markdown == "`python -m pyeye.mcp`"

    def test_ci_values(self, facts: dict[str, Bindable]) -> None:
        assert _fact(facts, "ci.coverage_threshold").value == 85
        assert "3.11" in _fact(facts, "ci.python_versions").value
        assert _fact(facts, "project.requires_python").value.startswith(">=")

    @staticmethod
    def _repo(tmp_path: Path, addopts: str, workflow: str, requires: str = ">=3.11") -> Path:
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        (tmp_path / ".github" / "workflows" / "ci.yml").write_text(workflow, encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text(
            f'[project]\nrequires-python = "{requires}"\n'
            'classifiers = ["Programming Language :: Python :: 3.11"]\n'
            f"[tool.pytest.ini_options]\naddopts = [{addopts}]\n",
            encoding="utf-8",
        )
        return tmp_path

    def test_consistent_sources_extract(self, tmp_path: Path) -> None:
        root = self._repo(tmp_path, '"--cov-fail-under=85"', "python-version: ['3.11']\n")

        assert {f.id: f.value for f in ci.extract(root)} == {
            "ci.coverage_threshold": 85,
            "ci.python_versions": ["3.11"],
            "project.python_versions": ["3.11"],
            "project.requires_python": ">=3.11",
        }

    def test_requires_python_must_match_the_oldest_classifier(self, tmp_path: Path) -> None:
        root = self._repo(tmp_path, '"--cov-fail-under=85"', "python-version: ['3.11']\n", ">=3.10")

        with pytest.raises(ci.ExtractionError, match="requires-python"):
            list(ci.extract(root))

    @pytest.mark.parametrize(
        ("addopts", "workflow", "match"),
        [
            ('"-q"', "python-version: ['3.11']\n", "exactly once"),
            ('"--cov-fail-under=85"', "--cov-fail-under=80\npython-version: ['3.11']\n", "80"),
            ('"--cov-fail-under=85"', "python-version: '3.11'\n", "one python-version list"),
            ('"--cov-fail-under=85"', "python-version: ['3.11', '3.12']\n", "claim"),
        ],
    )
    def test_ci_sources_that_changed_shape_fail(
        self, tmp_path: Path, addopts: str, workflow: str, match: str
    ) -> None:
        root = self._repo(tmp_path, addopts, workflow)

        with pytest.raises(ci.ExtractionError, match=match):
            list(ci.extract(root))


class TestRegistry:
    def test_every_extractor_yields_only_its_prefixes(self, facts: dict[str, Bindable]) -> None:
        prefixes = {p for e in registry.EXTRACTORS for p in e.prefixes}

        assert {i.split(".", 1)[0] for i in facts} == prefixes

    def test_a_shared_prefix_is_rejected(self) -> None:
        twice = [Extractor("a", ("x",), lambda _: []), Extractor("b", ("x",), lambda _: [])]

        with pytest.raises(ValueError, match="claimed by a and b"):
            build(ROOT, twice)

    def test_an_id_outside_the_prefixes_is_rejected(self) -> None:
        stray = [Extractor("a", ("x",), lambda _: [Fact("y.z", 1, "1")])]

        with pytest.raises(ValueError, match="outside its prefixes"):
            build(ROOT, stray)

    def test_a_view_over_an_unknown_fact_is_rejected(self) -> None:
        broken = [Extractor("a", ("x",), lambda _: [View("x.v", ("x.gone",), "")])]

        with pytest.raises(ValueError, match="unknown facts"):
            build(ROOT, broken)
