"""AST-first resolution of class-base references to canonical definition sites.

This is the Tier-2 building block for the subclasses cold-build fix (#405): a
**pure** function that resolves a base-class reference (as written in a module)
to the canonical *definition-site* dotted path, using AST-derived import tables
plus re-export following — **no Jedi inference**.

Design contract
---------------
- Returns the **definition site** (where ``class X`` physically appears), never
  a re-export path.
- Returns ``None`` when the AST cannot commit (conditional / ``TYPE_CHECKING``
  imports, externals/builtins, dynamic constructs). ``None`` means "ask Jedi" —
  the caller falls back to ``goto``, which remains the authority.
- It must NEVER return a *wrong* definition: the #405 Django measurement found
  0 disagreements with Jedi, and that safety property is what lets the caller
  trust the committed answer instead of verifying it.

Determinism (#419)
------------------
This AST resolution is **deterministic** — it is pure string/table logic with
no process-state dependence. Jedi forward ``goto``, the fallback for the
``None`` cases, is **not**: it can return different targets across fresh
processes for some bases (conditional imports, package re-exports), so any
``find_subclasses`` result whose membership depends on a ``goto``-resolved base
can vary run-to-run. Following ``import *`` re-exports here (#405) moved most
bases onto this deterministic path — measured ≈93% AST hits on Django,
``scripts/measure_subclass_fallback.py`` — shrinking but not eliminating the
non-deterministic surface. The residual is the second, forward-resolution
argument for a deterministic backend (#333), independent of the reverse-
reference one (#332).

The function is pure (no filesystem, no Jedi): it operates on pre-built tables,
so it is cheap and trivially testable. Building those tables from ASTs is a
separate concern.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

# build_import_table lives in the leaf module so canonicalization can share it
# without importing the analyzers layer (#712, #623 layering); re-exported here.
from pyeye._module_scope import (
    build_import_table as build_import_table,
    iter_module_scope_imports,
)
from pyeye._module_sentinel import DefinitionSentinel

# The star rule and star-source walk live in pyeye.star_exports, shared with
# resolve and the re-export binding index (#1010); re-exported here.
from pyeye.star_exports import (
    build_star_sources as build_star_sources,
    star_exported_from,
)

#: Kinds in ``module_defines`` that represent a real top-level definition site
#: (as opposed to ``"import"``, which marks a re-exported name to be followed).
_DEFINITION_KINDS = frozenset({"class", "func", "other"})

#: Runaway backstop on total nodes visited during one resolution. Real
#: re-export graphs are tiny; this only bounds pathological cases. The ``seen``
#: set is what actually guarantees termination on cyclic graphs.
_MAX_RESOLUTION_NODES = 1000


def _follow(
    path: str,
    import_tables: Mapping[str, Mapping[str, str]],
    module_defines: Mapping[str, Mapping[str, str]],
    star_sources: Mapping[str, list[str]],
    star_alls: Mapping[str, frozenset[str]],
    seen: set[str],
) -> str | None:
    """Follow re-export bindings (explicit and star) from *path* to a def site.

    Splits ``path`` into ``owning_module`` + ``leaf``:
    - a definition kind (class/func/other) is the answer;
    - ``"import"`` → *leaf* is an explicit re-export; follow its target;
    - otherwise → try the owning module's ``from x import *`` sources (a star
      re-export of *leaf*) and recurse into each in order; the first that
      resolves wins (explicit imports above already take precedence). A source
      is tried only when it star-exports *leaf* by the shared rule
      (:func:`pyeye.star_exports.star_exported_from`, #1010): its static
      ``__all__`` from *star_alls*, else a name not starting with ``_``.

    ``seen`` prevents mutual-re-export cycles (and is shared across star
    branches); ``_MAX_RESOLUTION_NODES`` is a runaway backstop.
    """
    if path in seen or len(seen) >= _MAX_RESOLUTION_NODES:
        return None
    seen.add(path)

    *mod_parts, leaf = path.split(".")
    owning_module = ".".join(mod_parts)
    kind = module_defines.get(owning_module, {}).get(leaf)
    if kind in _DEFINITION_KINDS:
        return f"{owning_module}.{leaf}"
    if kind == "import":
        nxt = import_tables.get(owning_module, {}).get(leaf)
        if not nxt:
            return None
        return _follow(nxt, import_tables, module_defines, star_sources, star_alls, seen)

    # leaf is neither defined nor an explicit import here — try star re-exports.
    for source_module in star_sources.get(owning_module, ()):
        if not star_exported_from(star_alls.get(source_module), leaf):
            continue
        resolved = _follow(
            f"{source_module}.{leaf}",
            import_tables,
            module_defines,
            star_sources,
            star_alls,
            seen,
        )
        if resolved is not None:
            return resolved
    return None


def resolve_base(
    module: str,
    base_dotted: str,
    import_tables: Mapping[str, Mapping[str, str]],
    module_defines: Mapping[str, Mapping[str, str]],
    star_sources: Mapping[str, list[str]] | None = None,
    star_alls: Mapping[str, frozenset[str]] | None = None,
) -> str | None:
    """Resolve a class-base reference to its canonical definition-site path.

    Args:
        module: Dotted name of the module that contains the class whose base is
            being resolved (provides the import scope for ``base_dotted``).
        base_dotted: The base as written in source — a bare name (``"Widget"``)
            or a dotted reference (``"widgets.Widget"``).
        import_tables: ``module -> {surface name: target dotted path}`` derived
            from each module's top-level imports (``as``-aliases included).
        module_defines: ``module -> {top-level name: kind}`` where ``kind`` is
            ``"class"``/``"func"``/``"other"`` for a real definition or
            ``"import"`` for a re-exported name.
        star_sources: Optional ``module -> [star-imported source modules]``
            (from :func:`build_star_sources`). When provided, a name re-exported
            via ``from x import *`` is followed into ``x``; omit it to disable
            star following (backward-compatible default).
        star_alls: Optional ``module -> static __all__`` for the modules that
            have one (:func:`pyeye.star_exports.static_all`). A star source
            missing here exports its names not starting with ``_`` (#1010).

    Returns:
        The canonical definition-site dotted path, or ``None`` if the AST cannot
        resolve it (caller should fall back to Jedi ``goto``).
    """
    head, *rest = base_dotted.split(".")
    tbl = import_tables.get(module, {})
    # When ``head`` is not imported under this surface name, the base is
    # tentatively a definition local to ``module`` (e.g. a sibling class used
    # as a base).
    full = ".".join([tbl[head], *rest]) if head in tbl else f"{module}.{base_dotted}"

    return _follow(full, import_tables, module_defines, star_sources or {}, star_alls or {}, set())


def build_module_defines(tree: ast.Module) -> dict[str, str]:
    """Build the top-level-name → kind table for one module's AST.

    Kinds: ``"class"`` / ``"func"`` for definitions, ``"other"`` for module-level
    assignments, and ``"import"`` for re-exported names (imported at top level).
    A real definition **wins** over a same-named import (definitions are assigned
    directly; imports use ``setdefault``), so a name defined here resolves here
    rather than following a shadowed re-export.

    Args:
        tree: Parsed module AST.

    Returns:
        ``{top-level name: kind}``.
    """
    defines: dict[str, str] = {}
    # Definitions come from the top-level statements, imports from the shared
    # unguarded walk (#630). Merge them back into source order: assignments and
    # imports both use setdefault, so the first binding of a name wins.
    statements: list[ast.stmt] = [
        node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign))
    ]
    statements.extend(iter_module_scope_imports(tree, include_guarded=False))
    statements.sort(key=lambda node: (node.lineno, node.col_offset))
    for node in statements:
        if isinstance(node, ast.ClassDef):
            defines[node.name] = "class"
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defines[node.name] = "func"
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defines.setdefault(target.id, "other")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                defines.setdefault(alias.asname or alias.name.split(".")[0], "import")
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                defines.setdefault(alias.asname or alias.name, "import")
    return defines


def _name_token_column(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Return the 0-indexed column of the *name* identifier, Jedi-style.

    AST nodes report ``col_offset`` at the ``class``/``def`` keyword; Jedi
    reports a definition at its name token. Offset past the keyword (and
    ``async ``) so dedup keys and the call-hierarchy ``get_references`` consumer
    see the same coordinates Jedi would.

    Args:
        node: The class or (async) function definition node.

    Returns:
        The 0-indexed column of the name identifier.
    """
    if isinstance(node, ast.ClassDef):
        return node.col_offset + len("class ")
    if isinstance(node, ast.AsyncFunctionDef):
        return node.col_offset + len("async def ")
    return node.col_offset + len("def ")


def extract_definitions(
    tree: ast.Module, module_name: str | None, module_path: Path
) -> list[DefinitionSentinel]:
    """Extract every definition site in one module's AST as ``DefinitionSentinel``s.

    Walks the module depth-first and yields one stand-in per **class**,
    **function** (incl. ``async def`` and nested methods/functions), and
    module-or-class-level **assignment** — plain (``x = 1``) or annotated
    (``x: int = 1`` and the annotation-only ``x: int``) — as ``"statement"``.
    ``full_name`` is
    composed from *module_name* plus lexical nesting (``pkg.mod.C.m``);
    ``line``/``column`` are the Jedi-exact name-token position so results dedup
    and round-trip identically to the ``project.search`` they replace (#457).
    Pure AST — no ``goto``/``infer``/Jedi search (#449).

    Assignments inside function bodies are skipped (locals are not project
    "definitions"); nested classes/functions are followed everywhere.

    Args:
        tree: Parsed module AST.
        module_name: Dotted module name for ``full_name`` composition (the
            namespace-prefixed name when the file is in a namespace package);
            ``None`` / ``""`` yields bare names.
        module_path: Absolute path to the module's source file.

    Returns:
        ``DefinitionSentinel``s in deterministic source order.
    """
    results: list[DefinitionSentinel] = []
    root = module_name or ""

    def _full(prefix: str, name: str) -> str:
        """Join a lexical *prefix* and *name* into a dotted full name."""
        return f"{prefix}.{name}" if prefix else name

    def _walk(body: list[ast.stmt], prefix: str, in_function: bool) -> None:
        """Recurse one scope's body, appending a sentinel per definition site."""
        for node in body:
            if isinstance(node, ast.ClassDef):
                fqn = _full(prefix, node.name)
                results.append(
                    DefinitionSentinel(
                        module_path=module_path,
                        full_name=fqn,
                        kind="class",
                        line=node.lineno,
                        column=_name_token_column(node),
                        docstring_text=ast.get_docstring(node) or "",
                        description=f"class {node.name}",
                    )
                )
                _walk(node.body, fqn, in_function=False)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fqn = _full(prefix, node.name)
                results.append(
                    DefinitionSentinel(
                        module_path=module_path,
                        full_name=fqn,
                        kind="function",
                        line=node.lineno,
                        column=_name_token_column(node),
                        docstring_text=ast.get_docstring(node) or "",
                        description=f"def {node.name}",
                    )
                )
                _walk(node.body, fqn, in_function=True)
            elif isinstance(node, ast.Assign) and not in_function:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        results.append(
                            DefinitionSentinel(
                                module_path=module_path,
                                full_name=_full(prefix, target.id),
                                kind="statement",
                                line=target.lineno,
                                column=target.col_offset,
                                description=f"{target.id} = ...",
                            )
                        )
            elif isinstance(node, ast.AnnAssign) and not in_function:
                # Annotated assignment (``x: int = 1``) — and the annotation-only
                # form (``x: int``), which Jedi still reports as a statement
                # definition. Only a bare-``Name`` target is a module/class-level
                # name binding (``self.x: int`` / ``d["k"]: int`` are not).
                if isinstance(node.target, ast.Name):
                    results.append(
                        DefinitionSentinel(
                            module_path=module_path,
                            full_name=_full(prefix, node.target.id),
                            kind="statement",
                            line=node.target.lineno,
                            column=node.target.col_offset,
                            description=f"{node.target.id}: ...",
                        )
                    )

    _walk(tree.body, root, in_function=False)
    return results
