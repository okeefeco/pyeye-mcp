"""Unit tests for the AST name->definitions extractor (#457) + NameSentinel (#450).

``extract_definitions`` walks one module's AST and yields a ``DefinitionSentinel``
per definition site (class / function / module-or-class-level statement), incl.
**nested** defs, with ``full_name`` composed from the module name + lexical
nesting and ``line``/``column`` at the **Jedi-exact name-token position**. Pure
AST: no ``goto`` / ``infer`` / Jedi search.

The three Jedi-``Name`` stand-ins (``ModuleSentinel``, ``ClassSentinel``,
``DefinitionSentinel``) share one ``NameSentinel`` base (#450).
"""

import ast
from pathlib import Path

import jedi

from pyeye._module_sentinel import (
    ClassSentinel,
    DefinitionSentinel,
    ModuleSentinel,
    NameSentinel,
)
from pyeye.analyzers.base_resolution import extract_definitions


def _extract(source: str, module_name: str = "pkg.mod", path: str = "pkg/mod.py"):
    return extract_definitions(ast.parse(source), module_name, Path(path))


def _by_name(defs, name):
    return [d for d in defs if d.name == name]


# --- #450: one shared base ---


def test_all_three_sentinels_share_the_name_base() -> None:
    assert issubclass(ModuleSentinel, NameSentinel)
    assert issubclass(ClassSentinel, NameSentinel)
    assert issubclass(DefinitionSentinel, NameSentinel)


def test_definition_sentinel_exposes_the_consumer_contract() -> None:
    d = _by_name(_extract("class Field:\n    pass\n"), "Field")[0]
    # The 4 _search_all_scopes consumers read exactly these.
    assert isinstance(d.module_path, Path)
    assert isinstance(d.line, int) and isinstance(d.column, int)
    assert isinstance(d.full_name, str) and isinstance(d.name, str)
    assert isinstance(d.type, str) and isinstance(d.description, str)
    assert isinstance(d.docstring(), str)
    assert d.get_signatures() == [] and d.infer() == []


# --- extract_definitions core ---


def test_top_level_class_yields_one_class_definition() -> None:
    fields = _by_name(_extract("class Field:\n    pass\n"), "Field")
    assert len(fields) == 1
    assert fields[0].type == "class"
    assert fields[0].full_name == "pkg.mod.Field"


def test_nested_method_full_name_includes_lexical_nesting() -> None:
    ms = _by_name(_extract("class C:\n    def m(self):\n        pass\n"), "m")
    assert len(ms) == 1
    assert ms[0].full_name == "pkg.mod.C.m"
    assert ms[0].type == "function"


def test_async_def_is_function_type() -> None:
    assert _by_name(_extract("async def go():\n    pass\n"), "go")[0].type == "function"


def test_module_level_assignment_is_statement_type() -> None:
    xs = _by_name(_extract("x = 1\n"), "x")
    assert len(xs) == 1
    assert xs[0].type == "statement"
    assert xs[0].full_name == "pkg.mod.x"


def test_docstring_extracted_for_class_and_function() -> None:
    src = 'class C:\n    """Class doc."""\n    def m(self):\n        """Method doc."""\n'
    defs = _extract(src)
    assert _by_name(defs, "C")[0].docstring() == "Class doc."
    assert _by_name(defs, "m")[0].docstring() == "Method doc."


def test_docstring_empty_when_absent() -> None:
    assert _by_name(_extract("def f():\n    return 1\n"), "f")[0].docstring() == ""


def test_extraction_is_deterministic() -> None:
    src = "class A:\n    pass\nclass B:\n    def m(self):\n        pass\n"

    def fields(t: ast.Module) -> list:
        return [
            (d.full_name, d.line, d.column)
            for d in extract_definitions(t, "pkg.mod", Path("pkg/mod.py"))
        ]

    assert fields(ast.parse(src)) == fields(ast.parse(src))


# --- the load-bearing one: line/column must equal Jedi's name-token position ---


def test_coordinates_match_jedi_name_token_position(tmp_path: Path) -> None:
    source = (
        "import abc\n"
        "\n"
        "class Field:\n"
        "    def to_python(self, value):\n"
        "        return value\n"
        "\n"
        "@property\n"
        "def cached():\n"
        "    return 1\n"
        "\n"
        "async def fetch():\n"
        "    return 2\n"
    )
    mod = tmp_path / "mod.py"
    mod.write_text(source)
    defs = extract_definitions(ast.parse(source), "mod", mod)

    script = jedi.Script(code=source, path=str(mod))
    jedi_pos = {
        n.name: (n.line, n.column)
        for n in script.get_names(all_scopes=True, definitions=True, references=False)
        if n.type in ("class", "function")
    }

    checked = 0
    for d in defs:
        if d.type not in ("class", "function"):
            continue
        assert d.name in jedi_pos, f"{d.name} missing from jedi names"
        assert (d.line, d.column) == jedi_pos[
            d.name
        ], f"{d.name}: extractor {(d.line, d.column)} != jedi {jedi_pos[d.name]}"
        checked += 1
    assert checked >= 4  # Field, to_python, cached, fetch
