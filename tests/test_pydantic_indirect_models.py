"""Pydantic models are found by definition site, transitively (#664).

A model is a project class that subclasses a Pydantic root (``BaseModel``,
``RootModel``, ``BaseSettings``) directly or through other project classes.
They come from the one class graph (``JediAnalyzer.find_subclasses``, #397), so
same-named models stay distinct. Only a root that doesn't resolve (its package
isn't installed where pyeye analyses) falls back to direct base-name matching.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from pyeye import (
    project_manager as project_manager_module,
    resolver,
)
from pyeye.plugins.pydantic import PydanticPlugin
from pyeye.project_manager import ProjectManager


@pytest.fixture(autouse=True)
def isolated_manager(monkeypatch: pytest.MonkeyPatch) -> Iterator[ProjectManager]:
    m = ProjectManager(max_projects=10)
    monkeypatch.setattr(project_manager_module, "_project_manager", m)
    yield m
    m.cleanup_all()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    app = tmp_path / "app"
    for pkg in (app, app / "a", app / "b"):
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "__init__.py").write_text("")
    (app / "base.py").write_text(
        "from pydantic import BaseModel\nimport pydantic\n\n\n"
        "class Timestamped(BaseModel):\n    created: int = 0\n\n\n"
        "class Direct(pydantic.BaseModel):\n    x: int = 1\n"
    )
    (app / "a" / "models.py").write_text(
        "from app.base import Timestamped\n\n\n"
        "class User(Timestamped):\n    name: str = ''\n\n\n"
        "class Admin(User):\n    level: int = 0\n"
    )
    (app / "b" / "models.py").write_text(
        "from pydantic import BaseModel\nfrom pydantic_settings import BaseSettings\n\n\n"
        "class User(BaseModel):  # same name, a different model\n    email: str = ''\n\n\n"
        "class Guest(User):\n    pass\n\n\n"
        "class Settings(BaseSettings):\n    debug: bool = False\n"
    )
    (app / "plain.py").write_text(
        "class BaseModel:  # NOT pydantic's\n    pass\n\n\n"
        "class Lookalike(BaseModel):\n    pass\n"
    )
    return tmp_path


def _where(models: list[dict], root: Path) -> set[tuple[str, str]]:
    return {(m["name"], Path(m["file"]).relative_to(root).as_posix()) for m in models}


@pytest.mark.asyncio
async def test_indirect_models_are_found(project: Path) -> None:
    models = await PydanticPlugin(str(project)).find_models("main")

    assert _where(models, project) >= {
        ("Timestamped", "app/base.py"),
        ("Direct", "app/base.py"),
        ("User", "app/a/models.py"),  # via Timestamped
        ("Admin", "app/a/models.py"),  # two hops
        ("User", "app/b/models.py"),
        ("Guest", "app/b/models.py"),
    }


@pytest.mark.asyncio
async def test_a_lookalike_base_is_not_a_model(project: Path) -> None:
    """``BaseModel`` resolves, so a class named like it but defined locally isn't one."""
    models = await PydanticPlugin(str(project)).find_models("main")

    assert ("Lookalike", "app/plain.py") not in _where(models, project)


@pytest.mark.asyncio
async def test_records_keep_their_shape(project: Path) -> None:
    models = await PydanticPlugin(str(project)).find_models("main")
    admin = next(m for m in models if m["name"] == "Admin")

    assert set(admin) == {
        "name",
        "file",
        "line",
        "type",
        "fields",
        "validators",
        "config",
        "base_classes",
    }
    assert admin["base_classes"] == ["User"]
    assert admin["type"] == "pydantic_model"
    assert [f["name"] for f in admin["fields"]] == ["level"]


@pytest.mark.asyncio
async def test_children_are_per_definition_site(project: Path) -> None:
    """Two models named ``User``: each lists only its own children (#720's note)."""
    plugin = PydanticPlugin(str(project))
    models = await plugin.find_models("main")
    by_file = {
        Path(m["file"]).relative_to(project).as_posix(): m for m in models if m["name"] == "User"
    }

    a_children = (await plugin.inheritance_for("User", by_file["app/a/models.py"], models))[
        "children"
    ]
    b_children = (await plugin.inheritance_for("User", by_file["app/b/models.py"], models))[
        "children"
    ]

    assert [c["name"] for c in a_children] == ["Admin"]
    assert [c["name"] for c in b_children] == ["Guest"]


class TestUnresolvableRootFallback:
    """Name matching is the weaker signal: only for a root that doesn't resolve."""

    @pytest.mark.asyncio
    async def test_basesettings_found_by_name_when_pydantic_settings_is_not_importable(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = resolver.resolve_handle

        def no_settings(path: str, analyzer: object) -> object:
            if path.endswith("BaseSettings"):
                return resolver.NotFound(reason="unresolved", detail="not installed (test)")
            return real(path, analyzer)

        monkeypatch.setattr(resolver, "resolve_handle", no_settings)
        models = await PydanticPlugin(str(project)).find_models("main")

        assert ("Settings", "app/b/models.py") in _where(models, project)

    @pytest.mark.asyncio
    async def test_name_matching_is_off_while_the_root_resolves(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With every root resolvable, the local ``BaseModel`` lookalike stays out."""
        from pyeye.plugins import pydantic as plugin_mod

        seen: list[str] = []
        real = plugin_mod.PydanticPlugin._name_matched_seeds

        def spy(
            self: PydanticPlugin, names: frozenset[str], *args: object, **kwargs: object
        ) -> object:
            seen.extend(sorted(names))
            return real(self, names, *args, **kwargs)

        monkeypatch.setattr(plugin_mod.PydanticPlugin, "_name_matched_seeds", spy)
        models = await PydanticPlugin(str(project)).find_models("main")

        assert "BaseModel" not in seen and "RootModel" not in seen
        assert ("Lookalike", "app/plain.py") not in _where(models, project)


@pytest.mark.asyncio
async def test_the_class_graph_is_built_once_for_the_whole_walk(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each hop is a lookup in the cached graph (#397), not a project rescan."""
    from pyeye.analyzers import project_graph

    builds = 0
    real = project_graph.get_class_graph

    def counting(project_key: str, build: object, *args: object, **kwargs: object) -> object:
        def counted() -> object:
            nonlocal builds
            builds += 1
            return build()  # type: ignore[operator]

        return real(project_key, counted, *args, **kwargs)  # type: ignore[arg-type]

    project_graph.invalidate()
    monkeypatch.setattr(project_graph, "get_class_graph", counting)
    models = await PydanticPlugin(str(project)).find_models("main")

    assert len(models) >= 6
    assert builds == 1
