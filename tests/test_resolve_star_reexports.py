"""``resolve`` follows ``from x import *`` re-exports to the definition (#1007).

``django.forms.Form`` is re-exported by ``django/forms/__init__.py`` through
``from django.forms.forms import *``, and wasn't found. A star import binds no
name the resolver could follow, so the project path stopped there.

The star follows Python: a name the source module lists in a static
``__all__``, else any name not starting with ``_``. An explicit binding wins
over a star, the first star source that resolves wins, and a star cycle ends.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve
from pyeye.star_exports import star_exported, static_all


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return _write(
        tmp_path / "proj",
        {
            "pkg/__init__.py": (
                "from .forms import *\nfrom .fields import *\nfrom .explicit import Shadow\n"
            ),
            "pkg/forms.py": (
                '__all__ = ("BaseForm", "Form", "Shadow")\n\n\n'
                "class BaseForm:\n    def clean(self):\n        pass\n\n\n"
                "class Form(BaseForm):\n    def is_valid(self):\n        pass\n\n\n"
                "class Hidden:\n    pass\n\n\n"
                "class Shadow:\n    pass\n"
            ),
            "pkg/fields.py": (
                "from .widgets import *\n\n\n"
                "class CharField:\n    pass\n\n\n"
                "class _Private:\n    pass\n"
            ),
            "pkg/widgets.py": "class TextInput:\n    pass\n",
            "pkg/explicit.py": "class Shadow:\n    pass\n",
            "absolute/__init__.py": "from pkg.widgets import *\n",
            "cyc/__init__.py": "from .a import *\n",
            "cyc/a.py": "from .b import *\n",
            "cyc/b.py": "from .a import *\n",
        },
    )


async def _handle(project: Path, identifier: str) -> str | None:
    result = await resolve(identifier, JediAnalyzer(str(project)))
    return result.get("handle") if result.get("found") else None


class TestResolve:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("identifier", "canonical"),
        [
            ("pkg.Form", "pkg.forms.Form"),  # listed in a static __all__
            ("pkg.BaseForm", "pkg.forms.BaseForm"),
            ("pkg.CharField", "pkg.fields.CharField"),  # no __all__: a public name
            ("pkg.TextInput", "pkg.widgets.TextInput"),  # a star of a star
            ("absolute.TextInput", "pkg.widgets.TextInput"),  # an absolute star source
            ("pkg.Form.is_valid", "pkg.forms.Form.is_valid"),  # a path under the star alias
        ],
    )
    async def test_a_star_re_export_resolves_to_its_definition(
        self, project: Path, identifier: str, canonical: str
    ) -> None:
        assert await _handle(project, identifier) == canonical

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "identifier",
        [
            "pkg.Hidden",  # defined in forms, but not in its __all__
            "pkg._Private",  # no __all__ in fields: an underscore name isn't star-exported
            "pkg.Nothing",
        ],
    )
    async def test_a_name_the_star_doesnt_export_is_not_found(
        self, project: Path, identifier: str
    ) -> None:
        assert await _handle(project, identifier) is None

    @pytest.mark.asyncio
    async def test_an_explicit_binding_beats_a_star(self, project: Path) -> None:
        """``forms`` star-exports a Shadow too; the explicit import names the definition."""
        assert await _handle(project, "pkg.Shadow") == "pkg.explicit.Shadow"

    @pytest.mark.asyncio
    async def test_a_star_cycle_ends(self, project: Path) -> None:
        assert await _handle(project, "cyc.Anything") is None

    @pytest.mark.asyncio
    async def test_other_tools_take_the_star_alias(self, project: Path) -> None:
        node = await inspect("pkg.Form", JediAnalyzer(str(project)))

        assert node["found"] is True and node["handle"] == "pkg.forms.Form"


class TestStarExportRule:
    """The one place the rule lives, for #1010 to reuse."""

    @staticmethod
    def _tree(source: str) -> ast.Module:
        return ast.parse(source)

    def test_a_static_all_is_read(self) -> None:
        tree = self._tree('__all__ = ["a", "b"]\n__all__ += ("c",)\n')

        assert static_all(tree) == frozenset({"a", "b", "c"})
        assert star_exported(tree, "c") and not star_exported(tree, "d")

    def test_no_all_means_every_public_name(self) -> None:
        tree = self._tree("x = 1\n")

        assert static_all(tree) is None
        assert star_exported(tree, "anything") and not star_exported(tree, "_hidden")

    def test_a_dynamic_all_falls_back_to_the_public_rule(self) -> None:
        """It can't be read without running the module, so the default rule applies."""
        tree = self._tree("__all__ = [n for n in dir() if n.isupper()]\n")

        assert static_all(tree) is None
        assert star_exported(tree, "LOUD") and not star_exported(tree, "_quiet")

    def test_an_empty_all_exports_nothing(self) -> None:
        tree = self._tree("__all__ = []\n")

        assert static_all(tree) == frozenset()
        assert not star_exported(tree, "anything")

    def test_an_underscore_name_in_all_is_exported(self) -> None:
        assert star_exported(self._tree('__all__ = ["_listed"]\n'), "_listed")
