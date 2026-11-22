"""docs-facts reads pyeye's facts statically, never by importing it (#1098, ruling C19).

:mod:`pyeye.docs_facts.static` folds module-level constants from ``ast``: literals,
names bound to literals (followed through ``from pyeye... import``), f-strings
over them, ``frozenset``/``set``/``tuple``/``list`` of a literal and set or
string operators. It never calls anything: any other expression is an
``ExtractionError`` naming where it is.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pyeye.docs_facts import static
from pyeye.docs_facts.facts import ExtractionError

ROOT = Path(__file__).resolve().parents[1]


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = tmp_path / "src/pyeye" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


class TestFold:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("X = 3", 3),
            ("X = ('a', 'b')", ("a", "b")),
            ("X: dict[str, int] = {'a': 1}", {"a": 1}),
            ("N = 'pyeye'\nX = f'.{N}.json'", ".pyeye.json"),
            ("X = frozenset({'a', 'b'})", frozenset({"a", "b"})),
            ("X = frozenset()", frozenset()),
            ("K = frozenset({'a', 'b'})\nX = K - {'a'}", frozenset({"b"})),
            ("X = 'a' 'b'", "ab"),
            ("X = ('a', 'b') + ('c',)", ("a", "b", "c")),
        ],
    )
    def test_folds(self, tmp_path: Path, source: str, expected: object) -> None:
        root = _repo(tmp_path, {"m.py": source + "\n"})
        assert static.constant(root, "pyeye.m", "X") == expected

    def test_follows_a_pyeye_import(self, tmp_path: Path) -> None:
        root = _repo(
            tmp_path,
            {
                "kinds.py": "KINDS = frozenset({'class', 'module'})\n",
                "m.py": "from pyeye.kinds import KINDS\nX = KINDS - {'module'}\n",
                "pkg/__init__.py": "",
                "pkg/n.py": "from ..kinds import KINDS\nX = KINDS | {'x'}\n",
            },
        )
        assert static.constant(root, "pyeye.m", "X") == frozenset({"class"})
        assert static.constant(root, "pyeye.pkg.n", "X") == frozenset({"class", "module", "x"})

    def test_a_class_attribute(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"m.py": "class C:\n    X = ('a',)\n"})
        assert static.constant(root, "pyeye.m", "C.X") == ("a",)

    @pytest.mark.parametrize(
        "source",
        [
            "X = len('a')",  # a call: never run
            "X = [p for p in 'ab']",  # a comprehension
            "import os\nX = os.sep",  # an attribute of a non-pyeye module
        ],
    )
    def test_refuses_what_it_would_have_to_run(self, tmp_path: Path, source: str) -> None:
        root = _repo(tmp_path, {"m.py": source + "\n"})
        with pytest.raises(ExtractionError, match=r"m\.py:\d+"):
            static.constant(root, "pyeye.m", "X")

    def test_a_missing_name_says_so(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"m.py": "Y = 1\n"})
        with pytest.raises(ExtractionError, match="no module-level 'X'"):
            static.constant(root, "pyeye.m", "X")


class TestCalls:
    def test_registry_calls_give_their_literal_arguments(self, tmp_path: Path) -> None:
        root = _repo(
            tmp_path,
            {"m.py": "def f(): pass\nX = (Step('a', 'one ' 'two', f), Step('b', 'three', f))\n"},
        )
        assert static.call_args(root, "pyeye.m", "X", 2) == [("a", "one two"), ("b", "three")]


def test_docstring(tmp_path: Path) -> None:
    root = _repo(
        tmp_path, {"m.py": "class C:\n    def f(self):\n        '''Line one.\n\n        More.'''\n"}
    )
    assert static.docstring(root, "pyeye.m", "C.f") == "Line one.\n\nMore."


def test_it_reads_this_repo_without_importing_it() -> None:
    assert static.constant(ROOT, "pyeye.constants", "CONFIG_FILE") == ".pyeye.json"


def test_a_module_namespace_folds_on_access(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"m.py": "N = 'x'\nX = f'{N}!'\n"})
    module = static.Module(root, "pyeye.m")
    assert (module.X, module.N) == ("x!", "x")
    assert module.file == root / "src/pyeye/m.py"


#: pyeye modules an extractor may import: the engine's own file-walking helpers,
#: never a source of facts.
_TOOLS = ("pyeye.docs_facts", "pyeye.path_utils", "pyeye.async_utils")

#: The fact sources still imported, each with the ruling that removes it. A
#: ratchet: it only shrinks, and an entry no longer imported fails too.
STILL_IMPORTED = {
    ("mcp_surface", "pyeye.scope_utils"): "#1098 PR B",
    ("mcp_surface", "pyeye.mcp"): "#1098 PR B",
    ("edges", "pyeye.mcp.operations"): "#1098 Q1: the server's descriptions read it live",
    ("scopes", "pyeye.scope_utils"): "#1098 Q1: the server's descriptions read it live",
    ("security", "pyeye.validation"): "#1098 Q2: _RESTRICTED_ANCESTORS",
}


def _pyeye_imports(path: Path) -> set[str]:
    """The pyeye modules *path* (an extractor) imports, anywhere in the file."""
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            if node.level:  # relative: extractors live at pyeye.docs_facts.extractors
                base = ["pyeye", "docs_facts", "extractors"][: 3 - node.level + 1]
                module = ".".join([*base, *(node.module.split(".") if node.module else [])])
            else:
                module = node.module or ""
            found.add(module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return {
        m for m in found if (m == "pyeye" or m.startswith("pyeye.")) and not m.startswith(_TOOLS)
    }


def test_extractors_import_no_fact_source_beyond_the_ratchet() -> None:
    """C19: facts are read from the source, so an extractor imports none of pyeye (#1098)."""
    folder = ROOT / "src/pyeye/docs_facts/extractors"
    imported = {
        (path.stem, module)
        for path in sorted(folder.glob("*.py"))
        for module in _pyeye_imports(path)
    }
    assert imported == set(STILL_IMPORTED)
