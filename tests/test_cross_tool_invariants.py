"""Cross-tool invariant fitness tests (#614, epic #629).

Every other test pins ONE primitive.  These pin what the primitives must agree
on, so that a fix landing in one copy of a capability can't leave its siblings
behind unnoticed (the drift pattern #629 describes):

1. **Emitted handles round-trip** — every stub handle any ``expand`` edge emits
   is found by ``inspect`` and ``resolve``, and both name the same canonical
   handle.
2. **Tools agree on a handle** — ``resolve``, ``resolve_at`` (at the definition
   position), ``inspect``, ``outline``, the ``expand`` source and the ``trace``
   root agree on ``found``, ``handle``, ``kind`` and ``scope``, under both a bare
   ``JediAnalyzer`` and ``ProjectManager().get_analyzer``.
3. **Counts match expand** — every key of ``inspect(h).edge_counts`` equals
   ``len(expand(h, edge)["stubs"])`` (generalises the #599 outline sweep).
4. **trace and expand agree** — trace expands a node along an edge only where
   ``expand`` says that edge is found and supported for it, emits only
   adjacents ``expand`` emits, and reports a root's wrong-kind edge in
   ``unsupported_edges``.

Allow-list contract
-------------------
Today's known gaps are listed in :data:`KNOWN_GAPS`, keyed by the exact
violation, with the issue whose fix removes the entry.  The comparison is
EXACT, in both directions:

- a violation NOT on the list fails (new drift);
- a listed violation that no longer reproduces ALSO fails — delete its entry
  (the fix landed; the list must shrink with it).

There is no blanket skip.  #629 is done when :data:`KNOWN_GAPS` is empty.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.jedi_worker import run_on_jedi_worker
from pyeye.mcp.operations.edges import EDGE_RESOLVERS
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline
from pyeye.mcp.operations.resolve import resolve, resolve_at
from pyeye.mcp.operations.trace import trace
from pyeye.project_manager import ProjectManager

_FIXTURES = Path(__file__).parent / "fixtures"
_REPO_ROOT = Path(__file__).parent.parent
_XTOOL = _FIXTURES / "cross_tool"

# ---------------------------------------------------------------------------
# The allow-list
# ---------------------------------------------------------------------------
#
# Key shapes (one per invariant family):
#   round_trip:   ("round_trip", corpus, handle, check)
#                 check ∈ {"inspect_found", "resolve_found", "same_handle",
#                          "stub_matches_inspect"}
#   counts:       ("counts", corpus, handle, edge)
#   superclasses: ("superclasses", corpus, class_handle)
#   agree:        ("agree", corpus, analyzer_mode, entry_id, field)
#                 field ∈ {"found", "handle", "kind", "scope"}
#   trace_expand: ("trace_expand", root, edge, node, check)
#                 check ∈ {"expanded_but_refused", "edge_not_in_expand",
#                          "wrong_kind_not_unsupported"}


def _round_trip(corpus: str, issue: str, checks: tuple[str, ...], *handles: str) -> dict:
    return {("round_trip", corpus, h, c): issue for h in handles for c in checks}


def _agree(corpus: str, entry_id: str, fld: str, issue: str, modes: tuple[str, ...]) -> dict:
    return {("agree", corpus, m, entry_id, fld): issue for m in modes}


_MISS = ("inspect_found", "resolve_found")
_BOTH_MODES = ("bare", "get_analyzer")

KNOWN_GAPS: dict[tuple[str, ...], str] = {
    # == 1. round trip: none since #623 slice 5 (#602) and #674 (#626),
    #    including the opt-in self-dogfood corpus (src/pyeye), except: =======
    # A stub-only module (#933): Jedi follows the .pyi, so expand(imports)
    # emits pkg.stubonly.S / .f, but resolve and inspect read .py sources only.
    # #933 option A (approved, post-v2.2.0) makes these resolve; this test then
    # fails until the entries are deleted.
    **_round_trip(
        "stub_only",
        "#933: stub-only module handles are emitted but not resolvable",
        _MISS,
        "pkg.stubonly.S",
        "pkg.stubonly.f",
    ),
    # == 3. counts: none today ==============================================
    # == 2. tools agree =====================================================
    # == 4. trace vs expand: none since #621.
}


# ---------------------------------------------------------------------------
# Exact allow-list comparison
# ---------------------------------------------------------------------------


def _assert_matches_allowlist(
    observed: dict[tuple[str, ...], str],
    prefix: tuple[str, ...],
    context: str,
    allowed: dict[tuple[str, ...], str] | None = None,
) -> None:
    """Fail unless *observed* violations equal the allow-list entries under *prefix*.

    Args:
        observed: violation key -> human-readable detail of what disagreed.
        prefix: the leading key components this test owns (e.g.
            ``("round_trip", "cross_tool")``); only allow-list entries with this
            prefix are compared, so each parametrised case owns its own slice.
        context: label for the failure message.
        allowed: the entries this case owns, when *prefix* alone can't select
            them (trace_expand keys aren't keyed by corpus; they're selected
            by root).  Defaults to every KNOWN_GAPS entry under *prefix*.
    """
    if allowed is None:
        allowed = {k: v for k, v in KNOWN_GAPS.items() if k[: len(prefix)] == prefix}
    new = sorted(set(observed) - set(allowed))
    fixed = sorted(set(allowed) - set(observed))
    lines: list[str] = []
    if new:
        lines.append(f"{len(new)} NEW cross-tool violation(s) in {context} (not allow-listed):")
        lines += [f"  {k!r}: {observed[k]}" for k in new]
    if fixed:
        lines.append(
            f"{len(fixed)} allow-listed violation(s) in {context} no longer reproduce — "
            "delete these KNOWN_GAPS entries:"
        )
        lines += [f"  {k!r}  # {allowed[k]}" for k in fixed]
    assert not lines, "\n".join(lines)


# ---------------------------------------------------------------------------
# Corpus sweep (shared by tests 1 and 3)
# ---------------------------------------------------------------------------

#: Fixture projects swept by tests 1 and 3.  Chosen to cover each project shape
#: pyeye supports: src-less and src layouts, re-exports, PEP 420 namespace
#: packages (top-level and nested), root-package projects (root has
#: ``__init__.py``), class hierarchies, and stdlib-heavy imports.
_SWEEP_CORPORA: dict[str, Path] = {
    name: _FIXTURES / name
    for name in (
        "cross_tool",
        "resolve_project",
        "typeref_basic",
        "containment",
        "canonicalization_multihop",
        "ns420",
        "ns420_nested",
        "superclasses_edge",
        "subclasses_resolution",
        "lookup_project",
        "determinism_subclasses",
        # A module that exists only as a .pyi stub (#933): edges emit its
        # handles, which nothing else accepts yet (see KNOWN_GAPS).
        "stub_only",
    )
}
#: A project plus a configured PEP 420 namespace repo OUTSIDE its root
#: (``app/.pyeye.json`` -> ``../acme-repo``).  #623 slice 2 regressed exactly
#: this shape (the repo's modules stopped resolving) with no corpus to notice.
_SWEEP_CORPORA["xns_repo"] = _FIXTURES / "xns_repo" / "app"

#: The full multi-repo namespace scenario (#667): three sibling repos stitched
#: into the PEP 420 ``corp`` namespace from outside a root-package project, via
#: ``namespaces`` (one a ``src/`` layout) and ``packages``.  See its README.
_MULTIREPO = _FIXTURES / "scenarios" / "multirepo_namespace"
_SWEEP_CORPORA["multirepo_namespace"] = _MULTIREPO / "app"
_MULTIREPO_MODULES = [
    "corp",
    "corp.core",
    "corp.core.models",
    "corp.tools",
    "corp.tools.widgets",
    "corp.tools.sub",
    "corp.tools.sub.helper",
    "corp.web",
    "corp.web.views",
]

#: Extra sweep seeds for modules outside the corpus root (``_module_seeds`` only
#: walks the root).
_EXTRA_SEEDS: dict[str, list[str]] = {
    "xns_repo": ["acme.tools", "acme.widgets"],
    "multirepo_namespace": _MULTIREPO_MODULES,
}


def _module_seeds(root: Path) -> list[str]:
    """Return the dotted module handle of every ``.py`` file under *root*.

    A ``src/`` layout is rooted at ``src``.  A root-package project (the root
    itself has ``__init__.py``) prefixes every module with the root's name —
    the canonical form ``resolve`` returns for such projects.
    """
    base = root / "src" if (root / "src").is_dir() else root
    prefix = [root.name] if (root / "__init__.py").exists() else []
    seeds: list[str] = []
    for path in sorted(base.rglob("*.py")):
        parts = prefix + list(path.relative_to(base).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            seeds.append(".".join(parts))
    return seeds


@dataclass
class _Sweep:
    """What one corpus sweep observed — plain data, so the tests share it."""

    #: source handle -> edge -> expand() result
    expanded: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    #: source handle -> inspect() result
    inspected: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: emitted stub handle -> (source handle, edge, stub) that first emitted it
    emitted: dict[str, tuple[str, str, dict[str, Any]]] = field(default_factory=dict)
    #: emitted stub handle -> (inspect() result, resolve() result)
    round_trips: dict[str, tuple[dict[str, Any], dict[str, Any]]] = field(default_factory=dict)


_SWEEP_CACHE: dict[str, _Sweep] = {}


async def _sweep(corpus: str, root: Path | None = None, follow_members: bool = True) -> _Sweep:
    """Expand every edge from every module (and its project members), then round-trip.

    Sources are each module's handle plus — with *follow_members* — transitively
    every project-scope ``members`` stub (classes, nested classes, functions...).
    Every stub any edge emits is then fed back to ``inspect`` and ``resolve``.
    Cached per corpus: tests 1 and 3 read the same observations.
    """
    if corpus in _SWEEP_CACHE:
        return _SWEEP_CACHE[corpus]
    root = root or _SWEEP_CORPORA[corpus]
    analyzer = ProjectManager().get_analyzer(str(root))
    sweep = _Sweep()
    queue = _module_seeds(root) + _EXTRA_SEEDS.get(corpus, [])
    while queue:
        source = queue.pop(0)
        if source in sweep.expanded:
            continue
        sweep.inspected[source] = await inspect(source, analyzer)
        per_edge = sweep.expanded[source] = {}
        for edge in EDGE_RESOLVERS:
            result = per_edge[edge] = await expand(source, edge, analyzer)
            for stub in result.get("stubs") or []:
                sweep.emitted.setdefault(stub["handle"], (source, edge, stub))
                if follow_members and edge == "members" and stub.get("scope") == "project":
                    queue.append(stub["handle"])
    for handle in sorted(sweep.emitted):
        sweep.round_trips[handle] = (
            await inspect(handle, analyzer),
            await resolve(handle, analyzer),
        )
    _SWEEP_CACHE[corpus] = sweep
    return sweep


# ---------------------------------------------------------------------------
# 1. Emitted handles round-trip
# ---------------------------------------------------------------------------


def _round_trip_violations(corpus: str, sweep: _Sweep) -> dict[tuple[str, ...], str]:
    out: dict[tuple[str, ...], str] = {}
    for handle, (ins, res) in sweep.round_trips.items():
        source, edge, stub = sweep.emitted[handle]
        origin = f"expand({source!r}, {edge!r})"
        if not ins.get("found"):
            out[("round_trip", corpus, handle, "inspect_found")] = f"from {origin}: inspect {ins}"
        if not res.get("found"):
            out[("round_trip", corpus, handle, "resolve_found")] = f"from {origin}: resolve {res}"
        if ins.get("found") and res.get("found"):
            names = {"emitted": handle, "inspect": ins.get("handle"), "resolve": res.get("handle")}
            if res.get("ambiguous") or len(set(names.values())) != 1:
                out[("round_trip", corpus, handle, "same_handle")] = (
                    f"from {origin}: {names} ambiguous={res.get('ambiguous', False)}"
                )
            # The stub IS a preview of inspect's node: it must not contradict it.
            stub_view = {"kind": stub.get("kind"), "scope": stub.get("scope")}
            node_view = {"kind": ins.get("kind"), "scope": ins.get("scope")}
            if stub_view != node_view:
                out[("round_trip", corpus, handle, "stub_matches_inspect")] = (
                    f"from {origin}: stub {stub_view} != inspect {node_view}"
                )
    return out


@pytest.mark.parametrize("corpus", sorted(_SWEEP_CORPORA))
async def test_emitted_handles_round_trip(corpus: str) -> None:
    """Every handle an edge emits is a live handle for inspect AND resolve (#602)."""
    sweep = await _sweep(corpus)
    assert sweep.emitted, f"{corpus}: the sweep emitted nothing — the corpus is not exercised"
    _assert_matches_allowlist(
        _round_trip_violations(corpus, sweep), ("round_trip", corpus), f"round-trip[{corpus}]"
    )


#: Opt-in: the self-dogfood corpus is ``src/pyeye`` itself (modules only).  It
#: takes ~8 minutes (≈0.5 s per round-trip of a failing external handle, ×600+),
#: and its external failures depend on the Python version and installed
#: packages, so it is not part of the default suite.  Its allow-list entries
#: were captured on CPython 3.12 / Linux.
_SELF_DOGFOOD_ENV = "PYEYE_SELF_DOGFOOD"


@pytest.mark.slow
@pytest.mark.timeout(1200)
async def test_emitted_handles_round_trip_self_dogfood() -> None:
    """Round-trip every handle ``src/pyeye``'s own modules emit (opt-in, slow)."""
    if os.environ.get(_SELF_DOGFOOD_ENV) != "1":
        pytest.skip(f"opt-in: set {_SELF_DOGFOOD_ENV}=1 (≈8 min)")
    sweep = await _sweep("src/pyeye", root=_REPO_ROOT, follow_members=False)
    _assert_matches_allowlist(
        _round_trip_violations("src/pyeye", sweep),
        ("round_trip", "src/pyeye"),
        "round-trip[src/pyeye]",
    )


# ---------------------------------------------------------------------------
# 3. inspect.edge_counts == len(expand.stubs), every edge, every source
# ---------------------------------------------------------------------------


def _count_violations(corpus: str, sweep: _Sweep) -> dict[tuple[str, ...], str]:
    out: dict[tuple[str, ...], str] = {}
    for handle, node in sweep.inspected.items():
        for edge, count in (node.get("edge_counts") or {}).items():
            result = sweep.expanded[handle].get(edge)
            if result is None:  # an edge inspect counts but expand doesn't know
                result = {"found": None, "note": "edge not in EDGE_RESOLVERS"}
            stubs = result.get("stubs")
            if not result.get("found") or result.get("unsupported") or stubs is None:
                out[("counts", corpus, handle, edge)] = f"count={count} but expand={result}"
            elif len(stubs) != count:
                out[("counts", corpus, handle, edge)] = f"count={count} != {len(stubs)} stubs"
    return out


@pytest.mark.parametrize("corpus", sorted(_SWEEP_CORPORA))
async def test_count_equals_expand_all_edges(corpus: str) -> None:
    """Every measured ``edge_counts`` key equals what ``expand`` lists (#599, generalised)."""
    sweep = await _sweep(corpus)
    counted = sum(len(n.get("edge_counts") or {}) for n in sweep.inspected.values())
    assert counted, f"{corpus}: no edge_counts measured — the corpus is not exercised"
    _assert_matches_allowlist(
        _count_violations(corpus, sweep), ("counts", corpus), f"counts[{corpus}]"
    )


# ---------------------------------------------------------------------------
# 3b. inspect's superclasses field IS the superclasses edge (#624)
# ---------------------------------------------------------------------------


def _superclasses_violations(corpus: str, sweep: _Sweep) -> dict[tuple[str, ...], str]:
    """Field == edge: the resolved bases in declaration order, raw text for the rest."""
    out: dict[tuple[str, ...], str] = {}
    for handle, node in sweep.inspected.items():
        if node.get("kind") != "class" or "superclasses" not in node:
            continue
        edge = sweep.expanded[handle].get("superclasses") or {}
        resolved = [s["handle"] for s in edge.get("stubs") or []]
        unresolved = edge.get("unresolved_superclasses")
        field = node["superclasses"]
        if unresolved is None:
            out[("superclasses", corpus, handle)] = f"edge has no unresolved_superclasses: {edge}"
            continue
        if [b for b in field if b not in unresolved] != resolved or sorted(
            b for b in field if b in unresolved
        ) != sorted(unresolved):
            out[("superclasses", corpus, handle)] = (
                f"field {field} != edge stubs {resolved} + unresolved {unresolved}"
            )
    return out


@pytest.mark.parametrize("corpus", sorted(_SWEEP_CORPORA))
async def test_superclasses_field_is_the_edge(corpus: str) -> None:
    """``inspect(cls).superclasses`` shows exactly what ``expand(cls, "superclasses")`` does."""
    sweep = await _sweep(corpus)
    _assert_matches_allowlist(
        _superclasses_violations(corpus, sweep), ("superclasses", corpus), f"superclasses[{corpus}]"
    )


# ---------------------------------------------------------------------------
# 2. Tools agree on a handle
# ---------------------------------------------------------------------------

_CORE = "xpkg/core.py"


@dataclass(frozen=True)
class _Entry:
    """One corpus handle and where ``resolve_at`` should land on it."""

    id: str
    identifier: str
    #: (fixture-relative file, 1-based line, 0-based column) of the definition
    #: name — or, for a stdlib entry, of the name on the importing line.
    position: tuple[str, int, int] | None = None


_XTOOL_ENTRIES = (
    _Entry("module", "xpkg.core", None),
    _Entry("package", "xpkg", None),
    _Entry("class", "xpkg.core.Widget", (_CORE, 14, 6)),
    _Entry("alias", "xpkg.Widget", (_CORE, 14, 6)),
    _Entry("class_attr", "xpkg.core.Widget.size", (_CORE, 17, 4)),
    _Entry("nested_class", "xpkg.core.Widget.Inner", (_CORE, 19, 10)),
    _Entry("nested_method", "xpkg.core.Widget.Inner.ping", (_CORE, 22, 12)),
    _Entry("method", "xpkg.core.Widget.greet", (_CORE, 26, 8)),
    _Entry("enum_member", "xpkg.core.Color.RED", (_CORE, 34, 4)),
    _Entry("function", "xpkg.core.make_widget", (_CORE, 37, 4)),
    _Entry("module_var", "xpkg.core.LOG", (_CORE, 11, 0)),
    _Entry("stdlib_module", "logging", (_CORE, 7, 7)),
    _Entry("stdlib_class", "pathlib.Path", (_CORE, 9, 20)),
    _Entry("stdlib_dotted_module", "os.path", None),
    _Entry("namespace_pkg", "xns", None),
    _Entry("namespace_module", "xns.portion", None),
    _Entry("namespace_fn", "xns.portion.thing", ("xns/portion.py", 4, 4)),
    _Entry("ghost_module", "xpkg.nope", None),
    _Entry("ghost_member", "xpkg.core.Widget.nope", None),
)

#: A ``src/`` layout: the root is NOT an import root, ``src`` is.
_SRC_LAYOUT_ENTRIES = (
    _Entry("package", "mypackage", None),
    _Entry("module", "mypackage.module", None),
    _Entry("function", "mypackage.module.my_function", ("src/mypackage/module.py", 4, 4)),
    _Entry("package_var", "mypackage.__version__", ("src/mypackage/__init__.py", 3, 0)),
)

#: A root-package project: the root directory itself has ``__init__.py``, so
#: the project root IS the top-level package (``lookup_project``).
_ROOT_PACKAGE_ENTRIES = (
    _Entry("root_package", "lookup_project", None),
    _Entry("module", "lookup_project.models", None),
    _Entry("class", "lookup_project.models.ServiceConfig", ("models.py", 8, 6)),
)

#: A project whose ``.pyeye.json`` configures a PEP 420 namespace repo outside
#: the project root (#623).  Positions are relative to the project root.
_XNS_REPO_ENTRIES = (
    _Entry("ns_package", "acme", None),
    _Entry("ns_module", "acme.tools", None),
    _Entry("ns_function", "acme.tools.helper", ("../acme-repo/acme/tools.py", 4, 4)),
    _Entry("ns_method", "acme.tools.Tool.use", ("../acme-repo/acme/tools.py", 12, 8)),
    _Entry("ns_subpackage", "acme.widgets", None),
    _Entry("ns_class", "acme.widgets.Widget", ("../acme-repo/acme/widgets/__init__.py", 4, 6)),
    _Entry("project_subclass", "main.FancyWidget", ("main.py", 7, 6)),
)

#: The #667 multi-repo namespace scenario.  Positions are relative to ``app/``.
_CORE_MODELS = "../corp-core/src/corp/core/models.py"
_WIDGETS = "../corp-tools/corp/tools/widgets.py"
_MULTIREPO_ENTRIES = (
    _Entry("root_package", "app", None),
    _Entry("project_function", "app.main.run", ("main.py", 11, 4)),
    _Entry("ns_package", "corp", None),
    _Entry("src_layout_portion", "corp.core", None),
    _Entry("src_layout_class", "corp.core.models.Base", (_CORE_MODELS, 8, 6)),
    _Entry("src_layout_method", "corp.core.models.Base.describe", (_CORE_MODELS, 14, 8)),
    _Entry("reexport", "corp.tools.Base", None),
    _Entry("packages_class", "corp.tools.widgets.Widget", (_WIDGETS, 14, 6)),
    _Entry("nested_module", "corp.tools.sub.helper", None),
    _Entry("flat_function", "corp.web.views.render", ("../corp-web/corp/web/views.py", 16, 4)),
    _Entry("ghost", "corp.nope", None),
)

#: corpus name -> (project root, entries)
_AGREE_CORPORA: dict[str, tuple[Path, tuple[_Entry, ...]]] = {
    "cross_tool": (_XTOOL, _XTOOL_ENTRIES),
    "src_layout": (_FIXTURES / "added_sys_path_project", _SRC_LAYOUT_ENTRIES),
    "root_package": (_FIXTURES / "lookup_project", _ROOT_PACKAGE_ENTRIES),
    "xns_repo": (_FIXTURES / "xns_repo" / "app", _XNS_REPO_ENTRIES),
    "multirepo_namespace": (_MULTIREPO / "app", _MULTIREPO_ENTRIES),
}

#: Corpora whose project root sits in a fixture dir with sibling repos it
#: configures by relative path: the whole parent is copied, so ``../`` resolves.
_AGREE_COPY_PARENT = frozenset({"xns_repo", "multirepo_namespace"})

_FIELDS = ("found", "handle", "kind", "scope")


def _view(found: Any, handle: Any = None, kind: Any = None, scope: Any = None) -> dict:
    return {"found": bool(found), "handle": handle, "kind": kind, "scope": scope}


async def _tool_views(
    entry: _Entry, root: Path, analyzer: JediAnalyzer
) -> dict[str, dict[str, Any]]:
    """What each primitive says about *entry*, normalised to found/handle/kind/scope.

    ``None`` means the tool does not report that field (e.g. ``expand`` has no
    kind/scope for its source); it is excluded from the comparison.
    """
    views: dict[str, dict[str, Any]] = {}
    r = await resolve(entry.identifier, analyzer)
    views["resolve"] = _view(
        r.get("found") and not r.get("ambiguous"), r.get("handle"), r.get("kind"), r.get("scope")
    )
    if entry.position is not None:
        rel, line, col = entry.position
        ra = await resolve_at(str(root / rel), line, col, analyzer)
        views["resolve_at"] = _view(
            ra.get("found") and not ra.get("ambiguous"),
            ra.get("handle"),
            ra.get("kind"),
            ra.get("scope"),
        )
    i = await inspect(entry.identifier, analyzer)
    views["inspect"] = _view(i.get("found"), i.get("handle"), i.get("kind"), i.get("scope"))
    o = await outline(entry.identifier, analyzer, max_depth=0)
    node = o.get("node") or {}
    views["outline"] = _view(
        o.get("found"), node.get("handle"), node.get("kind"), node.get("scope")
    )
    e = await expand(entry.identifier, "members", analyzer)
    views["expand"] = _view(e.get("found"), e.get("source"))
    t = await trace(entry.identifier, ["members"], analyzer, max_depth=0)
    if t["unresolved_roots"]:
        views["trace"] = _view(False)
    else:
        root_handle, root_node = next(iter(t["nodes"].items()))
        views["trace"] = _view(True, root_handle, root_node.get("kind"), root_node.get("scope"))
    return views


def _agree_violations(
    corpus: str, mode: str, entry: _Entry, views: dict
) -> dict[tuple[str, ...], str]:
    out: dict[tuple[str, ...], str] = {}
    for fld in _FIELDS:
        pool = views if fld == "found" else {k: v for k, v in views.items() if v["found"]}
        values = {tool: v[fld] for tool, v in pool.items() if v[fld] is not None}
        if len(set(values.values())) > 1:
            out[("agree", corpus, mode, entry.id, fld)] = f"{entry.identifier}: {values}"
    return out


def _analyzer(mode: str, root: Path) -> JediAnalyzer:
    if mode == "bare":
        return JediAnalyzer(str(root))
    return ProjectManager().get_analyzer(str(root))


@pytest.mark.parametrize("mode", ["bare", "get_analyzer"])
@pytest.mark.parametrize("corpus", sorted(_AGREE_CORPORA))
async def test_tools_agree_on_handle(corpus: str, mode: str, tmp_path: Path) -> None:
    """resolve / resolve_at / inspect / outline / expand / trace agree on one handle.

    Each case runs on a private COPY of its fixture (same directory name, since
    a root-package project's handles start with it).  Process-wide caches keyed
    by path leak state between a bare analyzer and a managed one on the same
    root (#618): without the copy, ``src_layout`` results depended on which
    mode ran first, and on other test files that use the same fixture.
    """
    source_root, entries = _AGREE_CORPORA[corpus]
    if corpus in _AGREE_COPY_PARENT:
        container = tmp_path.resolve() / source_root.parent.name
        shutil.copytree(source_root.parent, container)
        root = container / source_root.name
    else:
        root = tmp_path.resolve() / source_root.name
        shutil.copytree(source_root, root)
    analyzer = _analyzer(mode, root)
    observed: dict[tuple[str, ...], str] = {}
    for entry in entries:
        views = await _tool_views(entry, root, analyzer)
        observed.update(_agree_violations(corpus, mode, entry, views))
    _assert_matches_allowlist(observed, ("agree", corpus, mode), f"tools-agree[{corpus}/{mode}]")


# ---------------------------------------------------------------------------
# 4. trace and expand agree
# ---------------------------------------------------------------------------

#: (root, edge) pairs traced.  Covers project and stdlib imports, a namespace
#: package, class hierarchies, callees, and wrong-kind edges on each kind.
#:
#: Every case runs on the Jedi worker thread (#650), as the MCP tools do: an
#: ``imports`` hop into the stdlib (``io``/``weakref`` under ``logging``)
#: recurses ~1500 frames deep in Jedi, which overflows the default C stack on
#: Windows / CPython 3.11.  So no case has to be excluded for the stack.
_TRACE_CASES = tuple(
    (root, edge)
    for root in (
        "xpkg.core",
        "xpkg.text",
        "xpkg.consumer",
        "xns",
        "xpkg.core.Widget",
        "xpkg.core.Color",
        "xpkg.core.make_widget",
    )
    for edge in EDGE_RESOLVERS
)


async def _trace_expand_violations(
    root: str, edge: str, analyzer: JediAnalyzer
) -> dict[tuple[str, ...], str]:
    """Compare one ``trace(root, [edge])`` walk against ``expand`` hop by hop.

    Checked nodes are the root and its depth-1 adjacents.  Deeper nodes are
    stdlib internals for several roots, whose shape varies by Python version;
    keying the allow-list on them would make it platform-dependent.
    """
    out: dict[tuple[str, ...], str] = {}
    graph = await trace(root, [edge], analyzer, max_depth=2, max_nodes=500)
    root_expand = await expand(root, edge, analyzer)
    if (
        root_expand.get("found")
        and root_expand.get("unsupported")
        and edge not in {u["edge"] for u in graph["unsupported_edges"]}
    ):
        out[("trace_expand", root, edge, root, "wrong_kind_not_unsupported")] = (
            f"expand says unsupported ({root_expand.get('reason')}); trace "
            f"unsupported_edges={graph['unsupported_edges']}"
        )
    canonical_root = root_expand.get("source", root)
    checked = {canonical_root} | {s["handle"] for s in root_expand.get("stubs") or []}
    targets: dict[str, set[str]] = {}
    for e in graph["edges"]:
        if e["kind"] == edge and e["from"] in checked:
            targets.setdefault(e["from"], set()).add(e["to"])
    for node, tos in sorted(targets.items()):
        hop = root_expand if node == canonical_root else await expand(node, edge, analyzer)
        if not hop.get("found") or hop.get("unsupported"):
            out[("trace_expand", root, edge, node, "expanded_but_refused")] = (
                f"trace walked {node} -{edge}-> {sorted(tos)}; expand says {hop}"
            )
            continue
        extra = tos - {s["handle"] for s in hop.get("stubs") or []}
        if extra:
            out[("trace_expand", root, edge, node, "edge_not_in_expand")] = (
                f"trace has {node} -{edge}-> {sorted(extra)} that expand does not list"
            )
    return out


#: trace/expand roots in the #667 scenario: cross-repo hierarchy, calls and imports
#: (including the stdlib-importing roots, which need the worker's stack).
_MULTIREPO_TRACE_CASES = tuple(
    (root, edge)
    for root in (
        "app.main",
        "corp",
        "corp.core.models",
        "corp.core.models.Base",
        "corp.tools.widgets.Widget",
        "corp.web.views",
        "corp.web.views.render",
    )
    for edge in EDGE_RESOLVERS
)


@pytest.mark.parametrize(
    ("project", "cases"),
    [
        pytest.param(_XTOOL, _TRACE_CASES, id="cross_tool"),
        pytest.param(_MULTIREPO / "app", _MULTIREPO_TRACE_CASES, id="multirepo_namespace"),
    ],
)
async def test_trace_expand_agree(project: Path, cases: tuple[tuple[str, str], ...]) -> None:
    """trace walks exactly the hops expand supports, and surfaces wrong-kind edges."""
    analyzer = ProjectManager().get_analyzer(str(project))
    roots = {root for root, _ in cases}
    observed: dict[tuple[str, ...], str] = {}
    for root, edge in cases:
        # On the large-stack Jedi worker, like the MCP tools (#650): see _TRACE_CASES.
        observed.update(await run_on_jedi_worker(_trace_expand_violations(root, edge, analyzer)))
    owned = {k: v for k, v in KNOWN_GAPS.items() if k[0] == "trace_expand" and k[1] in roots}
    _assert_matches_allowlist(
        observed, ("trace_expand",), f"trace-expand[{project.name}]", allowed=owned
    )


# ---------------------------------------------------------------------------
# The allow-list comparison itself is exact (both directions)
# ---------------------------------------------------------------------------


class TestAllowListIsExact:
    """Guard the guard: the comparison must catch new AND stale entries."""

    _KEY = ("round_trip", "meta", "pkg.thing", "resolve_found")

    def test_listed_violation_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys.modules[__name__], "KNOWN_GAPS", {self._KEY: "#1"})
        _assert_matches_allowlist({self._KEY: "detail"}, ("round_trip", "meta"), "meta")

    def test_new_violation_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys.modules[__name__], "KNOWN_GAPS", {})
        with pytest.raises(AssertionError, match="NEW cross-tool violation"):
            _assert_matches_allowlist({self._KEY: "detail"}, ("round_trip", "meta"), "meta")

    def test_fixed_violation_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys.modules[__name__], "KNOWN_GAPS", {self._KEY: "#1"})
        with pytest.raises(AssertionError, match="no longer reproduce"):
            _assert_matches_allowlist({}, ("round_trip", "meta"), "meta")

    def test_other_prefixes_are_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        other = ("round_trip", "elsewhere", "pkg.thing", "resolve_found")
        monkeypatch.setattr(sys.modules[__name__], "KNOWN_GAPS", {other: "#1"})
        _assert_matches_allowlist({}, ("round_trip", "meta"), "meta")

    def test_every_entry_names_an_issue(self) -> None:
        for key, issue in KNOWN_GAPS.items():
            assert issue.startswith("#"), f"{key!r} must name the issue that removes it"
            assert key[0] in {"round_trip", "counts", "superclasses", "agree", "trace_expand"}, key
