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
#: ratchet: it only shrinks, and an entry no longer imported fails too. Empty
#: since #1098's closer: the server's live descriptions live in
#: ``pyeye.docs_facts.describe``, not in an extractor (Q1).
STILL_IMPORTED: dict[tuple[str, str], str] = {}


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


class TestMissesFailLoudly:
    """Every way a read can miss names what it was looking for."""

    def test_a_missing_module(self, tmp_path: Path) -> None:
        with pytest.raises(ExtractionError, match="pyeye.nope: no module file"):
            static.parse(tmp_path, "pyeye.nope")

    def test_a_missing_class(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"m.py": "X = 1\n"})
        with pytest.raises(ExtractionError, match="no class 'C'"):
            static.constant(root, "pyeye.m", "C.X")

    @pytest.mark.parametrize(
        "source",
        [
            "X = frozenset('a', 'b')",  # two arguments
            "X = frozenset(key='a')",  # a keyword
            "X = ('a',) - ('b',)",  # an operator the types don't support
            "X = 2 ** 3",  # an operator the folder doesn't evaluate
            "N = 1\nX = f'{N!r}'",  # an f-string conversion: formatting is code
        ],
    )
    def test_what_the_folder_refuses(self, tmp_path: Path, source: str) -> None:
        root = _repo(tmp_path, {"m.py": source + "\n"})
        with pytest.raises(ExtractionError, match=r"m\.py:\d"):
            static.constant(root, "pyeye.m", "X")

    def test_a_name_imported_from_outside_pyeye_is_not_followed(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"m.py": "import os\nfrom os import sep, pathsep\nX = sep\n"})
        with pytest.raises(ExtractionError, match="no module-level 'sep'"):
            static.constant(root, "pyeye.m", "X")

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("A = {'a'}\nX = A | {'b'}", {"a", "b"}),
            ("X = 'a' + 'b'", "ab"),
            ("A = frozenset({'a', 'b'})\nX = A & {'b'}", frozenset({"b"})),
            ("X = ['a', ('b', 1)]", ["a", ("b", 1)]),
            ("A = 'a'\nX = (A, 'b')", ("a", "b")),
            ("A = 'a'\nX = [A]", ["a"]),
            ("A = 'a'\nX = {A}", {"a"}),
            ("A = 'a'\nX = {A: (A, 1)}", {"a": ("a", 1)}),
        ],
    )
    def test_the_operators(self, tmp_path: Path, source: str, expected: object) -> None:
        root = _repo(tmp_path, {"m.py": source + "\n"})
        assert static.constant(root, "pyeye.m", "X") == expected

    @pytest.mark.parametrize(
        ("source", "message"),
        [
            ("X = 1", r"m\.py:1"),  # not a tuple of calls
            ("X = (len,)", r"m\.py:1"),  # an item that isn't a call
            ("Y = ()", "no module-level 'X'"),
        ],
    )
    def test_call_args_misses(self, tmp_path: Path, source: str, message: str) -> None:
        root = _repo(tmp_path, {"m.py": source + "\n"})
        with pytest.raises(ExtractionError, match=message):
            static.call_args(root, "pyeye.m", "X", 1)

    @pytest.mark.parametrize(
        ("source", "message"), [("X = 1", r"m\.py:1"), ("Y = {}", "no module-level 'X'")]
    )
    def test_dict_keys_misses(self, tmp_path: Path, source: str, message: str) -> None:
        root = _repo(tmp_path, {"m.py": source + "\n"})
        with pytest.raises(ExtractionError, match=message):
            static.dict_keys(root, "pyeye.m", "X")

    def test_dict_keys_reads_only_the_keys(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"m.py": "X = {'a': f, 'b': g}\n"})
        assert static.dict_keys(root, "pyeye.m", "X") == ["a", "b"]

    def test_a_missing_docstring_target(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"m.py": "class C:\n    pass\n"})
        with pytest.raises(ExtractionError, match="no 'C.f'"):
            static.docstring(root, "pyeye.m", "C.f")

    def test_a_module_namespace_has_no_dunders(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"m.py": "X = 1\n"})
        with pytest.raises(AttributeError):
            static.Module(root, "pyeye.m").__wrapped__  # noqa: B018 - the lookup is the test

    def test_a_guarded_import_is_not_followed(self, tmp_path: Path) -> None:
        """A ``try``/``if`` import binds nothing reliably, so it isn't folded through."""
        root = _repo(
            tmp_path,
            {
                "k.py": "K = 1\n",
                "m.py": "try:\n    from pyeye.k import K\nexcept ImportError:\n    K = 2\nX = K\n",
            },
        )
        with pytest.raises(ExtractionError, match="no module-level 'K'"):
            static.constant(root, "pyeye.m", "X")


def test_the_static_edge_registry_classifies_every_status(tmp_path: Path) -> None:
    """``edges._StaticRegistry.edge_status`` over declared sets, each branch (#1098)."""
    from pyeye.docs_facts.extractors import edges

    root = _repo(
        tmp_path,
        {
            "mcp/operations/edges.py": (
                "STATUS_IMPLEMENTED = 'implemented'\n"
                "STATUS_NOT_YET_IMPLEMENTED = 'not_yet_implemented'\n"
                "STATUS_DEFERRED_REFERENCE_BACKEND = 'deferred_reference_backend'\n"
                "STATUS_UNKNOWN_EDGE = 'unknown_edge'\n"
                "_IMPLEMENTED_EDGES = frozenset({'members'})\n"
                "_NOT_YET_IMPLEMENTED_EDGES = frozenset({'later'})\n"
                "_DEFERRED_REFERENCE_BACKEND_EDGES = frozenset({'callers'})\n"
                "EDGE_RESOLVERS = {'members': resolve_members}\n"
            )
        },
    )
    reg = edges._StaticRegistry(root)
    assert [reg.edge_status(e) for e in ("members", "later", "callers", "nope")] == [
        "implemented",
        "not_yet_implemented",
        "deferred_reference_backend",
        "unknown_edge",
    ]
    assert list(reg.EDGE_RESOLVERS) == ["members"]
    with pytest.raises(AttributeError):
        reg.__wrapped__  # noqa: B018 - the lookup is the test
