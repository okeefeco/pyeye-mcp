"""Single-site fitness tests for DECISIONS invariants (#615, epic #629).

Each decision in ``docs/decisions/entries/`` says a capability lives in ONE
place, but its Verify line samples only the site where the friction showed up.
These tests sweep ``src/pyeye`` with an AST scan, so a second copy can't
creep in unseen.

**The ratchet.** Today's violations sit on an EXACT allow-list. Each entry is
keyed by site (file relative to ``src/pyeye`` plus the qualified name of the
top-level function or method that contains it; a nested function counts as part
of its enclosing one) and names the #629 child issue that will remove it. The
test fails when:

* a NEW unlisted site appears (drift came back), or
* an allow-listed site no longer violates (it was fixed, so delete its entry).

``SANCTIONED`` names the one site where a capability is *meant* to live. It is
``None`` while the consolidation issue has yet to pick (or build) that site; the
consolidating PR sets it when it deletes the allow-list entries.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "pyeye"
TESTS_ROOT = REPO_ROOT / "tests"

#: ``(file relative to the scanned root, qualified function name)``.
Site = tuple[str, str]
#: A detector: given one top-level function/method node, does it violate?
Detector = Callable[[ast.AST], bool]

MODULE_LEVEL = "<module>"


# ---------------------------------------------------------------------------
# Scanning machinery
# ---------------------------------------------------------------------------


def _iter_units(tree: ast.Module) -> Iterator[tuple[str, ast.AST]]:
    """Yield ``(qualname, node)`` for each top-level function and method.

    Classes are descended (methods of nested classes included); functions are
    NOT, so a nested helper is attributed to the function that defines it.
    Module-level statements outside any function are yielded together as
    ``MODULE_LEVEL``.
    """
    loose: list[ast.stmt] = []

    def visit(body: list[ast.stmt], prefix: str, top: bool) -> Iterator[tuple[str, ast.AST]]:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield f"{prefix}{node.name}", node
            elif isinstance(node, ast.ClassDef):
                yield from visit(node.body, f"{prefix}{node.name}.", top=False)
            elif top:
                loose.append(node)

    yield from visit(tree.body, "", top=True)
    if loose:
        yield MODULE_LEVEL, ast.Module(body=loose, type_ignores=[])


def _scan(root: Path, detector: Detector, *, exclude: frozenset[str] = frozenset()) -> set[Site]:
    """Return every site under *root* where *detector* fires."""
    sites: set[Site] = set()
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel in exclude:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for qualname, unit in _iter_units(tree):
            if detector(unit):
                sites.add((rel, qualname))
    return sites


def _assert_ratchet(
    found: set[Site],
    sanctioned: Site | None,
    allowlist: dict[Site, str],
    invariant: str,
) -> None:
    """Assert *found* is exactly the sanctioned site plus the allow-list."""
    assert (
        sanctioned is None or sanctioned not in allowlist
    ), f"{invariant}: the sanctioned site {sanctioned} must not also be allow-listed."
    expected = set(allowlist) | ({sanctioned} if sanctioned else set())
    new = sorted(found - expected)
    fixed = sorted(expected - found)
    problems = []
    if new:
        problems.append(
            f"NEW violation(s) of {invariant}: {new}. Route the logic through the "
            "single sanctioned site instead of adding a copy."
        )
    if fixed:
        problems.append(
            f"No longer found for {invariant}: {fixed}. If you consolidated or deleted "
            "the copy, remove its allow-list entry (or update SANCTIONED) here."
        )
    assert not problems, "\n".join(problems)


def _is_ast_attr(node: ast.AST, names: frozenset[str]) -> bool:
    """``ast.<name>`` for one of *names*."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr in names
        and isinstance(node.value, ast.Name)
        and node.value.id == "ast"
    )


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def _is_synthetic_jedi_script(unit: ast.AST) -> bool:
    """A ``jedi.Script(code=...)`` with no ``path``: a synthetic-import inference.

    A Script built over a real file passes ``path=`` (``file_artifact_cache``);
    a synthetic one compiles a fabricated ``import x`` snippet with no file.
    """
    for node in ast.walk(unit):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_script = (isinstance(func, ast.Attribute) and func.attr == "Script") or (
            isinstance(func, ast.Name) and func.id == "Script"
        )
        if not is_script:
            continue
        keywords = {kw.arg for kw in node.keywords}
        if "code" in keywords and "path" not in keywords and len(node.args) < 2:
            return True
    return False


def _is_project_search_call(node: ast.AST) -> bool:
    """``project.search(...)`` or ``<x>.project.search(...)``."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    func = node.func
    if func.attr != "search":
        return False
    base = func.value
    return (isinstance(base, ast.Name) and base.id == "project") or (
        isinstance(base, ast.Attribute) and base.attr == "project"
    )


def _calls_project_search(unit: ast.AST) -> bool:
    return any(_is_project_search_call(node) for node in ast.walk(unit))


def _is_body_attr(node: ast.AST) -> bool:
    """``<name>.body``: a module's (or class's) top-level statement list."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "body"
        and isinstance(node.value, ast.Name)
        and isinstance(node.ctx, ast.Load)
    )


_IMPORT_NODES = frozenset({"Import", "ImportFrom"})


def _mentions_import_nodes(node: ast.AST) -> bool:
    return any(_is_ast_attr(sub, _IMPORT_NODES) for sub in ast.walk(node))


def _walks_body_for_imports(unit: ast.AST) -> bool:
    """A module-scope Import/ImportFrom walk over ``<tree>.body`` (#360).

    Fires on either form:

    * a ``for`` loop or comprehension iterating ``<tree>.body`` whose own body
      tests for ``ast.Import`` / ``ast.ImportFrom``; or
    * ``<tree>.body`` handed to a helper defined in the same function that tests
      for them (the recursive form ``_iter_module_scope_imports`` uses).

    A whole-tree ``ast.walk`` collecting every import is a different question
    (all imports, not module-scope ones) and is out of scope here.
    """
    local_import_walkers = {
        node.name
        for node in ast.walk(unit)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node is not unit
        and _mentions_import_nodes(node)
    }
    for node in ast.walk(unit):
        if isinstance(node, (ast.For, ast.AsyncFor)) and _is_body_attr(node.iter):
            if any(_mentions_import_nodes(stmt) for stmt in node.body):
                return True
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            if any(_is_body_attr(gen.iter) for gen in node.generators) and _mentions_import_nodes(
                node
            ):
                return True
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in local_import_walkers
            and any(_is_body_attr(arg) for arg in node.args)
        ):
            return True
    return False


def _attrs_read(unit: ast.AST) -> set[str]:
    """Attribute names read by *unit*, including ``getattr``/``hasattr`` by literal."""
    names: set[str] = set()
    for node in ast.walk(unit):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            names.add(node.attr)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"getattr", "hasattr"}
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            names.add(node.args[1].value)
    return names


def _builds_project_roots(unit: ast.AST) -> bool:
    """Assembles a project-roots list from ``project_path`` and ``source_roots``.

    Every roots list in ``src/pyeye`` starts from those two analyzer attributes
    (then optionally adds ``additional_paths`` / ``added_sys_path``), so reading
    both in one function is the signature of building one.
    """
    attrs = _attrs_read(unit)
    return "project_path" in attrs and "source_roots" in attrs


def _classifies_package_path(unit: ast.AST) -> bool:
    """Decides package-ness from a path: ``.name == "__init__.py"`` plus a
    ``.suffix == ".py"`` or ``.is_dir()`` test.

    Checking only ``.name == "__init__.py"`` (e.g. "is this importer a package
    ``__init__``?") is not a package predicate; the second test is what turns
    it into one.
    """
    names_init = other = False
    for node in ast.walk(unit):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Attribute):
            values = [c.value for c in node.comparators if isinstance(c, ast.Constant)]
            if node.left.attr == "name" and "__init__.py" in values:
                names_init = True
            if node.left.attr == "suffix" and ".py" in values:
                other = True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "is_dir"
        ):
            other = True
    return names_init and other


def _patches_project_search(unit: ast.AST) -> bool:
    """A test that stubs ``<x>.project.search`` (``patch.object(..., "search")``)."""
    for node in ast.walk(unit):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "object" or len(node.args) < 2:
            continue
        target, attr = node.args[0], node.args[1]
        if (
            isinstance(attr, ast.Constant)
            and attr.value == "search"
            and (
                (isinstance(target, ast.Attribute) and target.attr == "project")
                or (isinstance(target, ast.Name) and target.id == "project")
            )
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Allow-lists (each entry: site -> the #629 child issue that removes it)
# ---------------------------------------------------------------------------

# 1. Synthetic-import inference: ``jedi.Script(code=...)`` in exactly ONE
#    function, the resolver's (#623).  Empty allow-list since slice 3 removed
#    the ``resolve`` and ``canonicalization`` copies; kept so a new copy fails.
SYNTHETIC_IMPORT_SANCTIONED: Site | None = ("resolver.py", "_synthetic_import")
SYNTHETIC_IMPORT_ALLOWLIST: dict[Site, str] = {}

# 2. ``project.search(`` appears nowhere (#457: use the AST name-index).
#    Empty since #628 slice 2 deleted ``ProjectManager.search_all_projects``.
PROJECT_SEARCH_ALLOWLIST: dict[Site, str] = {}

# 2b. Tests that pin the banned ``project.search`` path as expected behaviour.
#     Keyed relative to ``tests/``.  Empty since #623 slice 2 removed inspect's
#     Case 3; kept so a new pinning test fails.
PROJECT_SEARCH_PINNING_TESTS_ALLOWLIST: dict[Site, str] = {}

# 3. Module-scope Import/ImportFrom walk over ``tree.body``: only
#    ``_module_scope.iter_module_scope_imports_guarded`` (#360, moved below both layers
#    in #630). #1081 made it yield each import's type-only flag; the unflagged
#    ``iter_module_scope_imports`` only delegates to it, so it is still ONE walk.
MODULE_SCOPE_WALK_SANCTIONED: Site | None = (
    "_module_scope.py",
    "iter_module_scope_imports_guarded",
)
MODULE_SCOPE_WALK_ALLOWLIST: dict[Site, str] = {}

# 4. Project-roots lists come from ONE helper: ``project_layout.project_roots``
#    (#625), which names each boundary's subset (SCOPE, TOP_LEVEL_PACKAGE,
#    MODULE_LOOKUP, NAMESPACE_PORTIONS).  The legacy copies were deleted (#628).
PROJECT_ROOTS_SANCTIONED: Site | None = ("project_layout.py", "project_roots")
PROJECT_ROOTS_ALLOWLIST: dict[Site, str] = {}

# 5. Package-ness is decided from a ``module_path`` in ONE predicate:
#    ``project_layout.package_kind`` (#625).  ``None`` is "unknown"; each caller
#    states what unknown means for it.
PACKAGE_PREDICATE_SANCTIONED: Site | None = ("project_layout.py", "package_kind")
PACKAGE_PREDICATE_ALLOWLIST: dict[Site, str] = {}

_EPIC_CHILDREN = frozenset({"#623", "#624", "#625", "#626", "#628", "#630"})
_ALL_ALLOWLISTS: dict[str, dict[Site, str]] = {
    "synthetic-import": SYNTHETIC_IMPORT_ALLOWLIST,
    "project.search": PROJECT_SEARCH_ALLOWLIST,
    "project.search pinning tests": PROJECT_SEARCH_PINNING_TESTS_ALLOWLIST,
    "module-scope walk": MODULE_SCOPE_WALK_ALLOWLIST,
    "project roots": PROJECT_ROOTS_ALLOWLIST,
    "package predicate": PACKAGE_PREDICATE_ALLOWLIST,
}


# ---------------------------------------------------------------------------
# The fitness tests
# ---------------------------------------------------------------------------


def test_synthetic_import_inference_lives_in_one_function() -> None:
    """``jedi.Script(code=...)`` synthetic imports appear in exactly one function."""
    _assert_ratchet(
        _scan(SRC_ROOT, _is_synthetic_jedi_script),
        SYNTHETIC_IMPORT_SANCTIONED,
        SYNTHETIC_IMPORT_ALLOWLIST,
        "one synthetic-import inference site",
    )


def test_project_search_is_never_called() -> None:
    """``jedi.Project.search`` is never called (#457: use the AST name-index)."""
    _assert_ratchet(
        _scan(SRC_ROOT, _calls_project_search),
        None,
        PROJECT_SEARCH_ALLOWLIST,
        "#457 no project.search",
    )


def test_no_test_pins_project_search_as_expected_behaviour() -> None:
    """No test stubs ``project.search`` to assert the banned path's result."""
    _assert_ratchet(
        _scan(
            TESTS_ROOT,
            _patches_project_search,
            exclude=frozenset({Path(__file__).relative_to(TESTS_ROOT).as_posix()}),
        ),
        None,
        PROJECT_SEARCH_PINNING_TESTS_ALLOWLIST,
        "#457 no test pins project.search",
    )


def test_module_scope_import_walk_is_shared() -> None:
    """Only ``_iter_module_scope_imports`` walks ``tree.body`` for imports (#360)."""
    _assert_ratchet(
        _scan(SRC_ROOT, _walks_body_for_imports),
        MODULE_SCOPE_WALK_SANCTIONED,
        MODULE_SCOPE_WALK_ALLOWLIST,
        "#360 one module-scope import walk",
    )


def test_project_roots_come_from_one_helper() -> None:
    """Project-roots lists are assembled in one helper."""
    _assert_ratchet(
        _scan(SRC_ROOT, _builds_project_roots),
        PROJECT_ROOTS_SANCTIONED,
        PROJECT_ROOTS_ALLOWLIST,
        "one project-roots helper",
    )


def test_package_predicate_lives_in_one_function() -> None:
    """Package-ness is decided from a path in one predicate (#625)."""
    _assert_ratchet(
        _scan(SRC_ROOT, _classifies_package_path),
        PACKAGE_PREDICATE_SANCTIONED,
        PACKAGE_PREDICATE_ALLOWLIST,
        "one package predicate",
    )


@pytest.mark.parametrize("name", sorted(_ALL_ALLOWLISTS))
def test_every_allowlist_entry_names_an_epic_child_issue(name: str) -> None:
    """Every allow-listed violation is owned by a #629 consolidation issue."""
    unowned = {
        site: issue for site, issue in _ALL_ALLOWLISTS[name].items() if issue not in _EPIC_CHILDREN
    }
    assert not unowned, f"{name}: entries without a #629 child issue: {unowned}"


# ---------------------------------------------------------------------------
# Detector self-tests: each detector fires on a violation and stays quiet on
# a near miss, so a refactor can't silently turn a sweep into a no-op.
# ---------------------------------------------------------------------------


def _fires(detector: Detector, source: str) -> set[str]:
    tree = ast.parse(source)
    return {qualname for qualname, unit in _iter_units(tree) if detector(unit)}


def test_iter_units_attributes_nested_functions_and_methods() -> None:
    source = (
        "X = jedi.Script(code='import a')\n"
        "class A:\n"
        "    class B:\n"
        "        def m(self): pass\n"
        "def outer():\n"
        "    def inner(): pass\n"
    )
    names = [qualname for qualname, _ in _iter_units(ast.parse(source))]
    assert names == ["A.B.m", "outer", MODULE_LEVEL]


def test_synthetic_script_detector() -> None:
    source = (
        "def synthetic(p):\n    return jedi.Script(code='import x', project=p)\n"
        "def real_file(src, p, path):\n    return jedi.Script(code=src, path=path, project=p)\n"
        "def bare():\n    return Script(code='import y')\n"
    )
    assert _fires(_is_synthetic_jedi_script, source) == {"synthetic", "bare"}


def test_project_search_detector() -> None:
    source = (
        "def a(analyzer):\n    analyzer.project.search('x')\n"
        "def b(project):\n    project.search('x', all_scopes=True)\n"
        "def c(regex, s):\n    regex.search(s)\n"
        "def d(analyzer):\n    analyzer.project.complete_search('x')\n"
    )
    assert _fires(_calls_project_search, source) == {"a", "b"}


def test_module_scope_walk_detector() -> None:
    source = (
        "def loop(tree):\n"
        "    for node in tree.body:\n"
        "        if isinstance(node, ast.ImportFrom): pass\n"
        "def comp(tree):\n"
        "    return [n for n in tree.body if isinstance(n, ast.Import)]\n"
        "def recursive(tree):\n"
        "    def _walk(nodes):\n"
        "        for n in nodes:\n"
        "            if isinstance(n, ast.Import): yield n\n"
        "    yield from _walk(tree.body)\n"
        "def symbols_only(tree):\n"
        "    for node in tree.body:\n"
        "        if isinstance(node, ast.ClassDef): pass\n"
        "    for node in ast.walk(tree):\n"
        "        if isinstance(node, ast.Import): pass\n"
    )
    assert _fires(_walks_body_for_imports, source) == {"loop", "comp", "recursive"}


def test_project_roots_detector() -> None:
    source = (
        "def roots(a):\n    return [a.project_path, *a.source_roots]\n"
        "def via_getattr(a):\n    return list(getattr(a, 'source_roots', [])) + [a.project_path]\n"
        "def only_project(a):\n    return a.project_path\n"
    )
    assert _fires(_builds_project_roots, source) == {"roots", "via_getattr"}


def test_package_predicate_detector() -> None:
    source = (
        "def by_suffix(p):\n"
        "    return p.name == '__init__.py' or p.suffix != '.py'\n"
        "def by_dir(p):\n"
        "    return p.name == '__init__.py' or p.is_dir()\n"
        "def importer_is_package(f):\n"
        "    return f.name == '__init__.py'\n"
        "def only_dir(p):\n"
        "    return p.is_dir()\n"
    )
    assert _fires(_classifies_package_path, source) == {"by_suffix", "by_dir"}


def test_patches_project_search_detector() -> None:
    source = (
        "def test_pins(analyzer):\n"
        "    with patch.object(analyzer.project, 'search', return_value=[]): pass\n"
        "def test_other(analyzer):\n"
        "    with patch.object(analyzer, 'search', return_value=[]): pass\n"
    )
    assert _fires(_patches_project_search, source) == {"test_pins"}


def test_ratchet_fails_on_new_and_on_fixed_sites() -> None:
    a, b, c = ("f.py", "a"), ("f.py", "b"), ("f.py", "c")
    _assert_ratchet({a, b}, a, {b: "#623"}, "demo")
    with pytest.raises(AssertionError, match="NEW violation"):
        _assert_ratchet({a, b, c}, a, {b: "#623"}, "demo")
    with pytest.raises(AssertionError, match="No longer found"):
        _assert_ratchet({a}, a, {b: "#623"}, "demo")
    with pytest.raises(AssertionError, match="No longer found"):
        _assert_ratchet({b}, a, {b: "#623"}, "demo")


# ---------------------------------------------------------------------------
# Check N (#545) extended to resolve / resolve_at: legacy not-found ratchet
# ---------------------------------------------------------------------------

RESOLVE_MODULE = SRC_ROOT / "mcp" / "operations" / "resolve.py"
_RESOLVE_ENTRY_POINTS = ("resolve", "resolve_at")


def _legacy_not_found_reasons_by_operation(source: str) -> set[tuple[str, str]]:
    """``(operation, reason)`` pairs a legacy ``{found: False, reason}`` can reach.

    A legacy result is a ``_NotFoundResult(found=False, reason="...")`` call with
    exactly those two keywords.  Reasons are propagated from each helper to the
    public entry points along same-module calls, so the set is what
    ``resolve`` / ``resolve_at`` can actually return.
    """
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    direct: dict[str, set[str]] = {}
    callees: dict[str, set[str]] = {}
    for name, fn in functions.items():
        direct[name] = set()
        callees[name] = set()
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id in functions:
                callees[name].add(node.func.id)
            if node.func.id != "_NotFoundResult":
                continue
            keywords = {kw.arg: kw.value for kw in node.keywords}
            reason = keywords.get("reason")
            if set(keywords) == {"found", "reason"} and isinstance(reason, ast.Constant):
                direct[name].add(str(reason.value))

    def reachable(name: str) -> set[str]:
        seen, stack, reasons = set(), [name], set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            reasons |= direct.get(current, set())
            stack.extend(callees.get(current, ()))
        return reasons

    return {
        (operation, reason)
        for operation in _RESOLVE_ENTRY_POINTS
        if operation in functions
        for reason in reachable(operation)
    }


def test_legacy_not_found_allowlist_matches_resolve() -> None:
    """The linter's N.4 allow-list equals what resolve / resolve_at emit today.

    When #626 moves a reason onto the shared ``{found, handle, reason, detail}``
    shape, its pair stops being produced and this fails until the entry is
    deleted from ``_LEGACY_NOT_FOUND_SHAPES``.  A new legacy reason fails too.
    """
    from tests.conformance.response_linter import _LEGACY_NOT_FOUND_SHAPES

    produced = _legacy_not_found_reasons_by_operation(RESOLVE_MODULE.read_text(encoding="utf-8"))
    listed = set(_LEGACY_NOT_FOUND_SHAPES)
    assert produced == listed, (
        f"Legacy not-found pairs drifted from the N.4 allow-list. "
        f"New (move onto the shared #545 shape instead): {sorted(produced - listed)}. "
        f"Fixed (delete from _LEGACY_NOT_FOUND_SHAPES): {sorted(listed - produced)}."
    )
    unowned = {k: v for k, v in _LEGACY_NOT_FOUND_SHAPES.items() if v not in _EPIC_CHILDREN}
    assert not unowned, f"N.4 entries without a #629 child issue: {unowned}"


def test_legacy_not_found_detector() -> None:
    source = (
        "def _helper():\n"
        "    return _NotFoundResult(found=False, reason='file_not_found')\n"
        "def _shared_shape():\n"
        "    return _NotFoundResult(found=False, handle='h', reason='unresolved', detail='d')\n"
        "async def resolve():\n"
        "    _helper(); _shared_shape()\n"
        "    return _NotFoundResult(found=False, reason='unresolved')\n"
        "async def resolve_at():\n"
        "    return _shared_shape()\n"
    )
    assert _legacy_not_found_reasons_by_operation(source) == {
        ("resolve", "file_not_found"),
        ("resolve", "unresolved"),
    }


@pytest.mark.parametrize("operation", _RESOLVE_ENTRY_POINTS)
def test_check_n_applies_to_resolve_operations(operation: str) -> None:
    """Check N covers resolve / resolve_at with their own echo (#545, #615, #626)."""
    from tests.conformance.response_linter import ConformanceViolation, lint_response

    echo = (
        {"identifier": "pkg.nope"}
        if operation == "resolve"
        else {"file": "pkg/nope.py", "line": 1, "column": 0}
    )
    # The operation's shared shape passes, for every reason in its set.
    for reason in ("unresolved", "file_not_found", "no_symbol_at_position"):
        lint_response({"found": False, **echo, "reason": reason, "detail": "no match"}, operation)
    # Echoing a handle for a non-handle input does not (#626).
    with pytest.raises(ConformanceViolation, match="N.2"):
        lint_response(
            {"found": False, "handle": "pkg.nope", "reason": "unresolved", "detail": "no match"},
            operation,
        )
    # The legacy two-key shape is no longer exempt: #626 emptied the N.4 list.
    with pytest.raises(ConformanceViolation, match="N.2"):
        lint_response({"found": False, "reason": "file_not_found"}, operation)
    with pytest.raises(ConformanceViolation, match="N.2"):
        lint_response({"found": False, "reason": "some_new_reason"}, operation)
    # A legacy shape padded with extra fields is not exempt.
    with pytest.raises(ConformanceViolation, match="N.2"):
        lint_response({"found": False, "reason": "unresolved", "candidates": []}, operation)
    # Missing ``found`` is rejected.
    with pytest.raises(ConformanceViolation, match="N.1"):
        lint_response({"reason": "unresolved"}, operation)
