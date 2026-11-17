"""A re-export collapses to its definition site, however it was imported (#857).

For ``from .thing import CloneThing`` in ``clonepkg/__init__.py``, Jedi names the
import binding ``clonepkg.CloneThing``, so step 4 matched the BINDING and kept
it: ``resolve("clonepkg.CloneThing")`` answered ``clonepkg.CloneThing`` at the
import line, although ``inspect("clonepkg.thing.CloneThing")`` lists that very
path among its ``re_exports``. The documented contract is that a re-export
collapses to its definition (``django.db.models.Model`` -> ``…base.Model``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.resolver import Resolved, resolve_handle

THING = "class CloneThing:\n    size = 1\n\n\ndef helper() -> int:\n    return 1\n"

#: ``__init__.py`` bodies that re-export from ``thing``.
INITS = {
    "relative": "from .thing import CloneThing, helper\n",
    "absolute": "from clonepkg.thing import CloneThing, helper\n",
    "relative_alias": "from .thing import CloneThing as CloneThing, helper as helper\n",
}


def _analyzer(tmp_path: Path, init: str) -> JediAnalyzer:
    pkg = tmp_path / "clonepkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(init, encoding="utf-8")
    (pkg / "thing.py").write_text(THING, encoding="utf-8")
    (pkg / "own.py").write_text("class Own:\n    pass\n", encoding="utf-8")
    return JediAnalyzer(tmp_path.as_posix())


@pytest.mark.parametrize("form", sorted(INITS))
@pytest.mark.parametrize(
    ("request_path", "handle"),
    [
        ("clonepkg.CloneThing", "clonepkg.thing.CloneThing"),
        ("clonepkg.helper", "clonepkg.thing.helper"),
    ],
)
def test_a_re_export_collapses_to_the_definition(
    tmp_path: Path, form: str, request_path: str, handle: str
) -> None:
    result = resolve_handle(request_path, _analyzer(tmp_path, INITS[form]))

    assert isinstance(result, Resolved), result
    assert result.handle == handle
    assert Path(result.anchor.module_path).name == "thing.py"


def test_a_definition_in_the_package_itself_stays(tmp_path: Path) -> None:
    """A real definition in ``__init__.py`` is not a re-export."""
    analyzer = _analyzer(tmp_path, "class Local:\n    pass\n")

    result = resolve_handle("clonepkg.Local", analyzer)

    assert isinstance(result, Resolved)
    assert result.handle == "clonepkg.Local"
    assert Path(result.anchor.module_path).name == "__init__.py"


def test_the_definition_path_itself_is_unchanged(tmp_path: Path) -> None:
    result = resolve_handle("clonepkg.thing.CloneThing", _analyzer(tmp_path, INITS["relative"]))

    assert isinstance(result, Resolved)
    assert result.handle == "clonepkg.thing.CloneThing"


def test_the_tools_agree(tmp_path: Path) -> None:
    import asyncio

    from pyeye.mcp.server import mcp

    _analyzer(tmp_path, INITS["relative"])
    p = tmp_path.as_posix()

    async def call(tool: str, **args: str) -> dict:
        result = await mcp.call_tool(tool, {**args, "project_path": p})
        assert not result.is_error, result.content
        return result.structured_content  # type: ignore[return-value]

    resolved = asyncio.run(call("resolve", identifier="clonepkg.CloneThing"))
    inspected = asyncio.run(call("inspect", handle="clonepkg.CloneThing"))
    definition = asyncio.run(call("inspect", handle="clonepkg.thing.CloneThing"))

    assert resolved["handle"] == inspected["handle"] == "clonepkg.thing.CloneThing"
    assert "clonepkg.CloneThing" in definition["re_exports"]


def test_dogfood_pyeyes_own_relative_re_export_collapses() -> None:
    """pyeye's own ``analyzers/__init__.py`` does ``from .jedi_analyzer import JediAnalyzer``.

    Found in the #864 review: it resolved to ``pyeye.analyzers.JediAnalyzer`` at
    ``analyzers/__init__.py``, not to its class.
    """
    repo = Path(__file__).parent.parent

    result = resolve_handle("pyeye.analyzers.JediAnalyzer", JediAnalyzer(repo.as_posix()))

    assert isinstance(result, Resolved), result
    assert result.handle == "pyeye.analyzers.jedi_analyzer.JediAnalyzer"
    assert Path(result.anchor.module_path).name == "jedi_analyzer.py"


def _tree(tmp_path: Path, files: dict[str, str]) -> JediAnalyzer:
    for rel, text in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return JediAnalyzer(tmp_path.as_posix())


def _resolved(path: str, analyzer: JediAnalyzer) -> Resolved:
    result = resolve_handle(path, analyzer)
    assert isinstance(result, Resolved), result
    return result


class TestShadowing:
    """#871 review: a local binding after a relative import is what ``q.A`` is at runtime."""

    @pytest.mark.parametrize(
        "init",
        [
            "from .src import A\n\n\nclass A:\n    local = 1\n",  # relative, then a class
            "from q.src import A\n\n\nclass A:\n    local = 1\n",  # absolute control
        ],
        ids=["relative", "absolute"],
    )
    def test_a_class_shadowing_an_import_is_the_local_class(
        self, tmp_path: Path, init: str
    ) -> None:
        analyzer = _tree(
            tmp_path, {"q/__init__.py": init, "q/src.py": "class A:\n    remote = 1\n"}
        )

        cls = _resolved("q.A", analyzer)
        member = _resolved("q.A.local", analyzer)

        assert cls.handle == "q.A"
        assert Path(cls.anchor.module_path).name == "__init__.py"
        assert member.handle == "q.A.local"  # the class and its members agree

    @pytest.mark.parametrize(
        "init",
        ["from .src import D\nD = 5\n", "from q.src import D\nD = 5\n"],
        ids=["relative", "absolute"],
    )
    def test_an_assignment_shadowing_an_import_is_the_local_binding(
        self, tmp_path: Path, init: str
    ) -> None:
        analyzer = _tree(tmp_path, {"q/__init__.py": init, "q/src.py": "D = 1\n"})

        result = _resolved("q.D", analyzer)

        assert result.handle == "q.D"
        assert Path(result.anchor.module_path).name == "__init__.py"

    def test_the_bare_name_stays_ambiguous(self, tmp_path: Path) -> None:
        import asyncio

        from pyeye.resolver import Ambiguous, resolve_name

        analyzer = _tree(
            tmp_path,
            {
                "q/__init__.py": "from .src import A\n\n\nclass A:\n    local = 1\n",
                "q/src.py": "class A:\n    remote = 1\n",
            },
        )

        result = asyncio.run(resolve_name("A", analyzer))

        assert isinstance(result, Ambiguous), result
        assert {c.handle for c in result.candidates} == {"q.A", "q.src.A"}


class TestSeveralBindings:
    def test_a_conditional_re_export_names_no_branch(self, tmp_path: Path) -> None:
        """``if/else`` imports of two definitions: no confident pick of either."""
        analyzer = _tree(
            tmp_path,
            {
                "r/__init__.py": (
                    "import sys\n\nif sys.platform == 'win32':\n    from .a import T\n"
                    "else:\n    from .b import T\n"
                ),
                "r/a.py": "class T:\n    pass\n",
                "r/b.py": "class T:\n    pass\n",
            },
        )

        result = _resolved("r.T", analyzer)

        assert result.handle == "r.T"

    def test_a_repeated_import_of_one_definition_still_collapses(self, tmp_path: Path) -> None:
        analyzer = _tree(
            tmp_path,
            {
                "r/__init__.py": (
                    "try:\n    from .a import T\nexcept ImportError:\n    from .a import T\n"
                ),
                "r/a.py": "class T:\n    pass\n",
            },
        )

        assert _resolved("r.T", analyzer).handle == "r.a.T"


class TestRelativeForms:
    def test_a_multi_hop_relative_chain_collapses(self, tmp_path: Path) -> None:
        analyzer = _tree(
            tmp_path,
            {
                "pkg/__init__.py": "from .sub import X\n",
                "pkg/sub/__init__.py": "from .impl import X\n",
                "pkg/sub/impl.py": "class X:\n    pass\n",
            },
        )

        assert _resolved("pkg.X", analyzer).handle == "pkg.sub.impl.X"
        assert _resolved("pkg.sub.X", analyzer).handle == "pkg.sub.impl.X"

    def test_from_dot_import_a_module(self, tmp_path: Path) -> None:
        analyzer = _tree(
            tmp_path,
            {
                "pkg/__init__.py": "from . import mod\n",
                "pkg/mod.py": "def f() -> None:\n    pass\n",
            },
        )

        result = _resolved("pkg.mod", analyzer)

        assert result.handle == "pkg.mod"
        assert result.kind == "module"

    def test_from_dot_dot_import_a_function(self, tmp_path: Path) -> None:
        analyzer = _tree(
            tmp_path,
            {
                "pkg/__init__.py": "def helper() -> int:\n    return 1\n",
                "pkg/sub/__init__.py": "from .. import helper\n",
            },
        )

        assert _resolved("pkg.sub.helper", analyzer).handle == "pkg.helper"


def test_an_unparseable_package_still_resolves(tmp_path: Path) -> None:
    """The AST can't be built (#703); Jedi still places the binding, uncollapsed."""
    analyzer = _tree(
        tmp_path,
        {
            "pkg/__init__.py": "from .a import T\n\ndef broken(:\n    pass\n",
            "pkg/a.py": "class T:\n    pass\n",
        },
    )

    result = resolve_handle("pkg.T", analyzer)

    assert isinstance(result, Resolved), result
