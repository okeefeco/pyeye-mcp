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
    build_star_sources,
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


# ---------------------------------------------------------------------------
# Star (`from x import *`) re-export following — optional star_sources arg
# ---------------------------------------------------------------------------


def test_resolve_base_follows_star_reexport() -> None:
    # 'app' imports Thing from pkg, which STAR-re-exports it from pkg.impl
    # (so Thing is NOT a direct name in pkg's import table or defines).
    import_tables = {"app": {"Thing": "pkg.Thing"}}
    module_defines = {"pkg": {}, "pkg.impl": {"Thing": "class"}}
    star_sources = {"pkg": ["pkg.impl"]}
    assert (
        resolve_base("app", "Thing", import_tables, module_defines, star_sources)
        == "pkg.impl.Thing"
    )


def test_resolve_base_without_star_sources_is_unchanged() -> None:
    # Same setup, no star_sources → still None (backward-compatible default).
    import_tables = {"app": {"Thing": "pkg.Thing"}}
    module_defines = {"pkg": {}, "pkg.impl": {"Thing": "class"}}
    assert resolve_base("app", "Thing", import_tables, module_defines) is None


def test_resolve_base_star_chain_followed_transitively() -> None:
    # pkg star-imports mid, mid star-imports impl which defines Thing.
    import_tables = {"app": {"Thing": "pkg.Thing"}}
    module_defines = {"pkg": {}, "mid": {}, "impl": {"Thing": "class"}}
    star_sources = {"pkg": ["mid"], "mid": ["impl"]}
    assert resolve_base("app", "Thing", import_tables, module_defines, star_sources) == "impl.Thing"


def test_resolve_base_star_cycle_terminates() -> None:
    # Mutual star imports must terminate with None, never hang.
    import_tables = {"app": {"X": "a.X"}}
    module_defines = {"a": {}, "b": {}}
    star_sources = {"a": ["b"], "b": ["a"]}
    assert resolve_base("app", "X", import_tables, module_defines, star_sources) is None


def test_resolve_base_direct_import_beats_star_source() -> None:
    # An explicit re-export in pkg shadows a star source that also defines Thing.
    import_tables = {"app": {"Thing": "pkg.Thing"}, "pkg": {"Thing": "real.Thing"}}
    module_defines = {
        "pkg": {"Thing": "import"},
        "pkg_star": {"Thing": "class"},
        "real": {"Thing": "class"},
    }
    star_sources = {"pkg": ["pkg_star"]}
    assert resolve_base("app", "Thing", import_tables, module_defines, star_sources) == "real.Thing"


def test_build_star_sources_absolute() -> None:
    assert build_star_sources(ast.parse("from pkg.impl import *"), "pkg", _resolve_relative) == [
        "pkg.impl"
    ]


def test_build_star_sources_relative_made_absolute() -> None:
    # `pkg` here is a top-level package __init__ re-exporting `from .impl import *`;
    # is_package=True anchors `.` at the package itself → pkg.impl (#426).
    assert build_star_sources(
        ast.parse("from .impl import *"), "pkg", _resolve_relative, is_package=True
    ) == ["pkg.impl"]


def test_build_star_sources_empty_without_star() -> None:
    assert (
        build_star_sources(ast.parse("from pkg.impl import Thing"), "pkg", _resolve_relative) == []
    )


def test_build_star_sources_relative_in_nested_package() -> None:
    # A nested package __init__ (`pkg.sub`) doing `from .impl import *` re-exports
    # from `pkg.sub.impl`. The old `level == len(parts)` heuristic resolved this
    # to `pkg.impl` (wrong), so find_subclasses could miss star-re-exported
    # subclasses. With the explicit package bit the source is correct (#426).
    assert build_star_sources(
        ast.parse("from .impl import *"), "pkg.sub", _resolve_relative, is_package=True
    ) == ["pkg.sub.impl"]
