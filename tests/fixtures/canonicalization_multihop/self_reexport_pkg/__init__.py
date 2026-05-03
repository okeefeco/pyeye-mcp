"""Self re-export — the package re-exports a symbol that the submodule already exports.

self_reexport_pkg/__init__.py imports from .submodule which has __all__ = ["Foo"].
This creates a potential cycle: the __init__.py re-exports Foo, and the submodule
already "exports" it via __all__.

The multi-hop walker MUST detect this cycle and terminate. The visited set in
_collect_re_exports_impl_multihop prevents infinite loops.

Expected result: resolve_canonical("self_reexport_pkg.Foo") ->
  Handle("self_reexport_pkg.submodule.Foo")
collect_re_exports gives: [Handle("self_reexport_pkg.Foo")]
"""

from self_reexport_pkg.submodule import Foo

__all__ = ["Foo"]
