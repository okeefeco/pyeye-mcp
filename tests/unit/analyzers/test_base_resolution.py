"""Unit tests for AST-first base-class resolution (#405, Tier-2).

``resolve_base`` maps a class-base reference (as written in a module) to its
**canonical definition-site** dotted path, using AST-derived import tables plus
re-export following. It returns ``None`` when the AST cannot commit — the caller
then falls back to Jedi ``goto`` (the authority).

Contract pinned by these tests:
- When it commits, it returns the **definition site**, never a re-export path.
- It NEVER returns a *wrong* definition (the #405 Django measurement found 0
  disagreements; ``None`` is the only allowed "I don't know").
"""

import ast
from pathlib import Path

from pyeye.analyzers.base_resolution import (
    build_import_table,
    build_module_defines,
    resolve_base,
)
from pyeye.import_analyzer import ImportAnalyzer

# Real production relative-import resolver (pure string logic; project_path unused).
_resolve_relative = ImportAnalyzer(Path("."))._resolve_relative_import


def test_direct_import_resolves_to_definition_site() -> None:
    # module 'app' does `from lib import Widget`; lib defines `class Widget`.
    import_tables = {"app": {"Widget": "lib.Widget"}}
    module_defines = {"lib": {"Widget": "class"}}
    assert resolve_base("app", "Widget", import_tables, module_defines) == "lib.Widget"


def test_aliased_import_resolves_through_the_alias() -> None:
    # `from lib import Widget as W; class X(W)` — the surface name is the alias.
    import_tables = {"app": {"W": "lib.Widget"}}
    module_defines = {"lib": {"Widget": "class"}}
    assert resolve_base("app", "W", import_tables, module_defines) == "lib.Widget"


def test_dotted_reference_resolves_via_module_alias() -> None:
    # `from lib import widgets; class X(widgets.Widget)`.
    import_tables = {"app": {"widgets": "lib.widgets"}}
    module_defines = {"lib.widgets": {"Widget": "class"}}
    assert (
        resolve_base("app", "widgets.Widget", import_tables, module_defines) == "lib.widgets.Widget"
    )


def test_reexport_is_followed_to_the_definition_site() -> None:
    # app imports `pkg.Widget`, but pkg/__init__ re-exports it from pkg.core.
    # Resolution must follow the re-export to the DEFINITION site, not stop at
    # the re-export path.
    import_tables = {
        "app": {"Widget": "pkg.Widget"},
        "pkg": {"Widget": "pkg.core.Widget"},  # re-export binding
    }
    module_defines = {
        "pkg": {"Widget": "import"},  # re-exported, not defined here
        "pkg.core": {"Widget": "class"},  # actual definition
    }
    assert resolve_base("app", "Widget", import_tables, module_defines) == "pkg.core.Widget"


def test_unresolvable_base_returns_none() -> None:
    # Base not imported and not locally defined (e.g. a star-imported or external
    # name). AST must punt with None so the caller falls back to Jedi.
    import_tables = {"app": {}}
    module_defines = {"app": {}}
    assert resolve_base("app", "Mystery", import_tables, module_defines) is None


def test_reexport_cycle_returns_none_not_infinite_loop() -> None:
    # Pathological mutual re-export must terminate with None, never hang.
    import_tables = {
        "a": {"X": "b.X"},
        "b": {"X": "a.X"},
    }
    module_defines = {
        "a": {"X": "import"},
        "b": {"X": "import"},
    }
    assert resolve_base("a", "X", import_tables, module_defines) is None


# ---------------------------------------------------------------------------
# build_import_table — surface name -> target dotted path, from a module AST
# ---------------------------------------------------------------------------


def _table(src: str, module: str = "app") -> dict[str, str]:
    return build_import_table(ast.parse(src), module, _resolve_relative)


def test_import_table_from_import() -> None:
    assert _table("from lib import Widget")["Widget"] == "lib.Widget"


def test_import_table_aliased_name() -> None:
    assert _table("from lib import Widget as W")["W"] == "lib.Widget"


def test_import_table_plain_import_binds_head() -> None:
    # `import lib.widgets` binds the head `lib`; `lib.widgets.X` resolves via it.
    assert _table("import lib.widgets")["lib"] == "lib"


def test_import_table_aliased_module() -> None:
    assert _table("import lib.widgets as lw")["lw"] == "lib.widgets"


def test_import_table_relative_import_made_absolute() -> None:
    # module `pkg.sub` doing `from .base import Model` → pkg.base.Model
    table = build_import_table(ast.parse("from .base import Model"), "pkg.sub", _resolve_relative)
    assert table["Model"] == "pkg.base.Model"


def test_import_table_skips_star() -> None:
    assert _table("from lib import *") == {}


# ---------------------------------------------------------------------------
# build_module_defines — top-level name -> kind, from a module AST
# ---------------------------------------------------------------------------


def _defines(src: str) -> dict[str, str]:
    return build_module_defines(ast.parse(src))


def test_defines_class() -> None:
    assert _defines("class Widget:\n    pass\n")["Widget"] == "class"


def test_defines_function() -> None:
    assert _defines("def helper():\n    pass\n")["helper"] == "func"


def test_defines_module_assignment() -> None:
    assert _defines("CONFIG = 1")["CONFIG"] == "other"


def test_defines_marks_reexport_as_import() -> None:
    assert _defines("from lib import Widget")["Widget"] == "import"


def test_definition_wins_over_prior_import_of_same_name() -> None:
    # `from lib import Widget` then `class Widget` — the real definition wins,
    # so the name resolves here, not to the (shadowed) re-export.
    assert _defines("from lib import Widget\nclass Widget:\n    pass\n")["Widget"] == "class"
