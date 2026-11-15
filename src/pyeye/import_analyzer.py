"""Relative-import resolution: the one rule every caller shares (#426)."""

import logging

logger = logging.getLogger(__name__)


def resolve_relative_import(
    current_module: str,
    imported_module: str | None,
    level: int,
    is_package: bool = False,
) -> str | None:
    """Resolve a relative import to an absolute module path.

    Single source of truth for relative-import resolution (#426): the
    ``find_subclasses`` AST resolution tables call it directly, and
    :meth:`JediAnalyzer._resolve_relative_import` (``find_importers``)
    delegates here.

    The anchor is the importer's **containing package**, which depends on
    whether the importer is a package ``__init__`` — this is why *is_package*
    must be passed explicitly rather than inferred from the dotted string (a
    module ``pkg.sub`` and a package ``pkg.sub`` are indistinguishable by name).
    This mirrors Python's own ``importlib`` semantics:

    - a regular module ``pkg.sub.mod`` (``is_package=False``) has containing
      package ``pkg.sub``; ``level=1`` (``.``) anchors there, each extra level
      strips one more trailing component.
    - a package ``pkg.sub`` (``is_package=True``, its ``__init__``) IS its own
      package; ``level=1`` anchors at ``pkg.sub`` itself, ``level=2`` at ``pkg``.
    - resolving above the top-level package yields ``None`` (a relative import
      that walks past the root, which Python rejects as an ``ImportError``).

    Args:
        current_module: The importer's dotted module name (for a package
            ``__init__`` this is the package name itself).
        imported_module: Relative module text after the dots (``None`` for
            ``from . import X``).
        level: Number of leading dots (0 = absolute import, returned unchanged).
        is_package: ``True`` when the importer is a package ``__init__`` (its
            name already denotes the package, so it is not stripped).

    Returns:
        Absolute module name, or ``None`` if it cannot be resolved.
    """
    if level <= 0:
        # Absolute import: the imported module is already absolute.
        return imported_module
    parts = current_module.split(".") if current_module else []
    # The containing package: a package __init__ IS its own package; a regular
    # module's package is its parent (drop the module's own trailing component).
    anchor_parts = parts if is_package else parts[:-1]
    strip = level - 1
    if strip > len(anchor_parts):
        # Walks above the top-level package — Python rejects this.
        return None
    base = anchor_parts[: len(anchor_parts) - strip] if strip else anchor_parts
    suffix = imported_module.split(".") if imported_module else []
    combined = base + suffix
    return ".".join(combined) if combined else None
