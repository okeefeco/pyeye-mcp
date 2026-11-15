"""The subclasses edge searches the whole project scope (#669).

``resolve_subclasses`` searched ``scope="main"`` only, so a subclass in a
configured additional package or namespace repo was missed: ``expand(Base,
"subclasses")`` answered a measured ``[]`` while ``expand(Widget,
"superclasses")`` reported ``Base``.  Configured packages and namespaces are
``project`` scope (#623), so the edge must search them too — and nothing
outside them (standalone script directories are not configured project code).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pyeye.mcp.operations.expand import expand
from pyeye.project_manager import ProjectManager


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _main_project(root: Path, config: dict) -> Path:
    app = root / "app"
    _write(app / ".pyeye.json", json.dumps(config))
    _write(app / "core" / "__init__.py")
    _write(app / "core" / "models.py", 'class Base:\n    """The base."""\n')
    _write(
        app / "core" / "local.py",
        'from core.models import Base\n\n\nclass Local(Base):\n    """In main."""\n',
    )
    return app


@pytest.mark.asyncio
async def test_subclass_in_configured_package_is_found(tmp_path: Path) -> None:
    app = _main_project(tmp_path, {"packages": ["../ext"]})
    _write(tmp_path / "ext" / "extpkg" / "__init__.py")
    _write(
        tmp_path / "ext" / "extpkg" / "widgets.py",
        'from core.models import Base\n\n\nclass Widget(Base):\n    """In a configured package."""\n',
    )
    analyzer = ProjectManager().get_analyzer(app.as_posix())

    result = await expand("core.models.Base", "subclasses", analyzer)

    handles = {s["handle"] for s in result["stubs"]}
    assert handles == {"core.local.Local", "extpkg.widgets.Widget"}
    widget = await expand("extpkg.widgets.Widget", "superclasses", analyzer)
    assert [s["handle"] for s in widget["stubs"]] == ["core.models.Base"]  # the two edges agree


@pytest.mark.asyncio
async def test_subclass_in_configured_namespace_is_found(tmp_path: Path) -> None:
    app = _main_project(tmp_path, {"namespaces": {"corp": ["../corp-tools"]}})
    _write(
        tmp_path / "corp-tools" / "corp" / "tools" / "widgets.py",
        'from core.models import Base\n\n\nclass Gadget(Base):\n    """In a namespace repo."""\n',
    )
    analyzer = ProjectManager().get_analyzer(app.as_posix())

    result = await expand("core.models.Base", "subclasses", analyzer)

    assert "corp.tools.widgets.Gadget" in {s["handle"] for s in result["stubs"]}
