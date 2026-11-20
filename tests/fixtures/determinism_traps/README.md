# determinism_traps

The fixture for the edge determinism conformance test (#452,
`tests/test_edge_determinism.py`). Every implemented edge has at least one
source here, and it holds the two known cross-process traps:

- `pkg/shim.py` is a project try/except import shim: `Local` is
  `pkg._fast.Local` or `pkg._slow.Local`, and `pkg.users.ShimChild` subclasses it.
- `pkg.users.ThreadState` subclasses `threading.local`, which the standard
  library binds through the same kind of shim (`_thread._local` or
  `_threading_local.local`).
- `pkg/rebind.py` binds `Cursor` with an if/else on a runtime condition: a class
  in one branch, `object` in the other (django's `postgresql.base.Cursor`
  pattern). `pkg.users.CursorChild` imports it at module level, and
  `pkg.users.make_local.LocalCursor` inside a function.

Jedi's goto can return both branches of a shim, in an order that differs
between processes (#419). `subclasses` used to key a base by the first one, so
its answer for these classes changed between processes (#1057). Now an
ambiguous base (a shim, or a rebinding in one file) is unresolved in both
`subclasses` and `superclasses`.
