Resolution and Determinism
==========================

This page is the written contract for *how pyeye resolves things*: which engine
answers which kind of question, how a name becomes a canonical handle, and what
pyeye says when it can't answer. It collects a principle that grew out of many
separate fixes. The reasoning behind each rule lives in its decision entry
under ``docs/decisions/entries/``; this page states the rules and points there.

Three tiers, by kind of question
--------------------------------

**1. Structural facts that are literally in the source: AST is the ground truth.**
  Who subclasses ``X``, who imports this module, what a relative import names,
  what a package or class contains. These are read from the Python AST and are
  never re-derived through Jedi, which would add only non-determinism.

  - ``imported_by`` is a pure-AST reverse scan (#436).
  - Relative-import resolution has one AST seam, where there used to be two
    divergent resolvers (#426).
  - ``find_subclasses`` resolves bases AST-first. Jedi forward ``goto`` is the
    documented, measured fallback, needed for roughly 7% of bases on Django
    (#419).
  - ``expand(subclasses)`` builds its stubs from AST facts. It used to
    re-derive a Jedi ``Name`` per subclass, which brought #419's
    non-determinism back (#445).

**2. Semantic inference: Jedi, bounded.**
  Types, cross-file ``goto``, signatures, re-export canonicalisation. Jedi is
  the engine. Each use is bounded, and where Jedi's answer can be wrong or
  non-deterministic the edge documents that tail rather than hiding it.

**3. Reverse queries Jedi answers unreliably: deferred, never faked.**
  Callers, references and reverse ``edge_counts`` are not answered with Jedi's
  ``get_references``, which is non-deterministically wrong. They are left to a
  deterministic backend (#333) or to the client's LSP. The legacy tools that
  answered them confidently and wrongly were removed in 2.0 (#505).

The static-edge determinism invariant
-------------------------------------

  A static structural edge is **deterministic** and is built from
  **AST-derived facts**. It never re-derives each adjacent through Jedi.

This holds in practice for ``imported_by`` and ``subclasses``, and each edge
has its own regression test. #452 tracks making it a registry-level check, so
that a new edge can't reintroduce the #445 pattern without a test failing.

One canonical handle resolver
-----------------------------

Every exact-path lookup goes through one resolver,
``pyeye.resolver.resolve_handle(path) -> Resolved | NotFound`` (#623). That
covers ``inspect``, the ``outline`` root, the ``expand`` source, ``trace``
roots and interior nodes, ``resolve`` and ``resolve_at``, typeref forward refs,
and the external targets of the ``imports`` edge. Each tool echoes the handle
the resolver returns.

**Canonical means definition site.** ``pkg.Thing`` re-exported from
``pkg._impl`` resolves to ``pkg._impl.Thing``, and every tool reports that
handle.

The strategy chain; the first step that applies wins:

1. **Project module**: a module file in the project.
2. **PEP 420 namespace package**: a configured namespace with no file.
3. **External module**: an installed or stdlib module that Jedi infers under
   exactly this name.
4. **Project definition**: placed in the deepest project module along the
   path, matched by Jedi ``full_name``, following re-export aliases
   (``package.Thing`` → ``package._impl.Thing``, #431/#429).
5. **External definition**, in two parts:

   a. the definition Jedi's ``goto`` lands on, accepted only when it sits at
      **exactly** the requested path. This places ``typing.TYPE_CHECKING``,
      whose value infers to ``bool``. A target at a different path is refused,
      so ``collections.abc.Mapping`` never becomes ``typing.Mapping`` (#506,
      #544).
   b. guarded inference: an inferred definition whose name equals the leaf
      (``pathlib.Path`` → ``pathlib._local.Path`` on 3.13).

Steps 3 and 5 run only outside the project, and step 4 only inside it, so
external inference can never answer for a project path (#506). Scope comes from
one rule, ``scope_for``: everything the user configured (the project, its
packages and namespaces) is ``project``; site-packages and the stdlib are
``external``.

What is never a binding: the target of an attribute assignment
(``self.x = …``, ``obj.attr = …``). Jedi gives it the same ``full_name`` as a
local of the method, or as a module member, but it binds nothing in that scope,
so it is never placed and never listed as a member (#567). Instance attributes
are not modelled yet (#565).

Bare names
----------

A bare (dot-free) name goes through ``pyeye.resolver.resolve_name``, which
returns ``Resolved``, ``Ambiguous`` (with candidates) or ``NotFound``. The
first rule that applies wins:

1. **Shadow**: a top-level package of that name under more than one project
   root stays ambiguous (#423).
2. **An exact top-level module wins**: ``resolve("functools")`` is stdlib
   ``functools`` even if the project defines something named ``functools``
   (#602, #623). The project's symbol is reached by its dotted handle.
3. **The name index**: every project module, top-level definition or nested
   class with that name, each canonicalised through ``resolve_handle``. One
   left is the answer; several are ambiguous (#457).
4. **Members, as a fallback**: only if rules 1–3 find nothing, every method
   or class-body attribute with that name, decided the same way. A top-level
   name therefore hides same-named methods. Dunder names (``__eq__``) are never
   members here, because every class defines them (#508).

Methods and attributes are never in the name index itself. Rule 4 reads a
separate member index, built in the same pass and invalidated with it.

The environment the resolver sees
---------------------------------

Correctness must not depend on cache size or on Jedi internals:

- The name index is whole-project and lives outside the parsed-file LRU, so an
  eviction can never make a definition silently disappear (#457).
- parso's in-memory parse cache is never garbage-collected, because its GC
  dropped stdlib files Jedi still held and made ``asyncio.Queue`` unresolvable
  in large runs (#684).
- Jedi's own private subprocess directory is never on the analysed
  ``sys.path``; otherwise its files read as top-level modules
  (``resolve("functions")``) and shadowed configured packages (#722).

Saying "I don't know" honestly
------------------------------

A miss is never dressed up as an answer:

- Every primitive returns one not-found shape,
  ``{found: false, <lookup echo>, reason, detail}``, with ``reason`` drawn
  from a closed per-operation set and ``detail`` naming the next step (#626).
- The resolver never guesses. A path it can't place is not-found, and it never
  hands back Jedi's raw ``full_name``, which no other tool would accept.
- Absence is not zero. An omitted field means "not measured"; ``[]`` means
  "measured, none". ``trace`` keeps unresolved roots and interior callees in
  always-present fields (#488) rather than dropping them, and ``imports`` /
  ``imported_by`` list what they couldn't resolve or name (#494, #668).
- A file the server's interpreter can't parse is never silently skipped: a
  source whose own file fails reports ``unparseable`` (#703), and the reverse
  scans ``subclasses`` / ``imported_by`` list such files in
  ``unparseable_files`` (#729).

Where the details live
----------------------

- Decision entries: ``docs/decisions/entries/``. Start with "One canonical
  handle resolver" and "Bare name: an exact top-level module wins" (#623).
- Edge design specs: ``docs/superpowers/specs/`` (expand core, imported_by).
- The agent-facing summary is in the ``python-explore`` skill
  (``skills/python-explore/SKILL.md``).
