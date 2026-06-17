"""AST-first resolution of class-base references to canonical definition sites.

This is the Tier-2 building block for the subclasses cold-build fix (#405): a
**pure** function that resolves a base-class reference (as written in a module)
to the canonical *definition-site* dotted path, using AST-derived import tables
plus re-export following — **no Jedi inference**.

Design contract
---------------
- Returns the **definition site** (where ``class X`` physically appears), never
  a re-export path.
- Returns ``None`` when the AST cannot commit (star/`__all__` re-exports,
  externals/builtins, dynamic constructs). ``None`` means "ask Jedi" — the
  caller falls back to ``goto``, which remains the authority.
- It must NEVER return a *wrong* definition: the #405 Django measurement found
  0 disagreements with Jedi, and that safety property is what lets the caller
  trust the committed answer instead of verifying it.

The function is pure (no filesystem, no Jedi): it operates on pre-built tables,
so it is cheap and trivially testable. Building those tables from ASTs is a
separate concern.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Mapping

#: Kinds in ``module_defines`` that represent a real top-level definition site
#: (as opposed to ``"import"``, which marks a re-exported name to be followed).
_DEFINITION_KINDS = frozenset({"class", "func", "other"})

#: Hard ceiling on re-export hops. Real chains are short; this only bounds
#: pathological mutual re-exports so resolution always terminates.
_MAX_HOPS = 20


def _follow(
    path: str,
    import_tables: Mapping[str, Mapping[str, str]],
    module_defines: Mapping[str, Mapping[str, str]],
) -> str | None:
    """Follow re-export bindings from *path* to a definition site, or ``None``.

    Each hop splits ``path`` into ``owning_module`` + ``leaf``:
    - a definition kind (class/func/other) is the answer;
    - ``"import"`` means *leaf* is re-exported — jump to its target and continue;
    - anything else (unknown leaf, external module) yields ``None``.

    A ``seen`` set bounds mutual re-export cycles; ``_MAX_HOPS`` bounds depth.
    """
    seen: set[str] = set()
    for _ in range(_MAX_HOPS):
        if path in seen:
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
            path = nxt
            continue
        return None
    return None


def resolve_base(
    module: str,
    base_dotted: str,
    import_tables: Mapping[str, Mapping[str, str]],
    module_defines: Mapping[str, Mapping[str, str]],
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

    return _follow(full, import_tables, module_defines)


def build_import_table(
    tree: ast.Module,
    module: str,
    resolve_relative: Callable[[str, str | None, int], str | None],
) -> dict[str, str]:
    """Build the surface-name → target-path table for one module's AST.

    Only **top-level** imports are considered (the scope a class base resolves
    in). ``as``-aliases are captured under the alias; ``import a.b.c`` binds the
    head ``a``; relative imports are made absolute via *resolve_relative*; star
    imports are skipped (their names can't be resolved statically — the resolver
    will punt to Jedi for bases that rely on them).

    Args:
        tree: Parsed module AST.
        module: Dotted name of this module (for relative-import resolution).
        resolve_relative: ``(module, imported_module_or_None, level) -> abs path``
            — typically ``ImportAnalyzer._resolve_relative_import``.

    Returns:
        ``{surface name: target dotted path}``.
    """
    table: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    table[alias.asname] = alias.name
                else:
                    head = alias.name.split(".")[0]
                    table[head] = head
        elif isinstance(node, ast.ImportFrom):
            base = (
                resolve_relative(module, node.module, node.level) if node.level > 0 else node.module
            )
            for alias in node.names:
                if alias.name == "*":
                    continue
                surface = alias.asname or alias.name
                table[surface] = f"{base}.{alias.name}" if base else alias.name
    return table


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
    for node in tree.body:
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
