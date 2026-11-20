# determinism_traps

The fixture for the edge determinism conformance test (#452,
`tests/test_edge_determinism.py`). Every implemented edge has at least one
source here, and it holds the two known cross-process traps:

- `pkg/shim.py` is a project try/except import shim: `Local` is
  `pkg._fast.Local` or `pkg._slow.Local`, and `pkg.users.ShimChild` subclasses it.
- `pkg.users.ThreadState` subclasses `threading.local`, which the standard
  library binds through the same kind of shim (`_thread._local` or
  `_threading_local.local`).

Jedi's goto picks one branch of a shim per process (#419). `subclasses` keys its
bases through that goto, so its answer for these classes can differ between
processes (#1057).
