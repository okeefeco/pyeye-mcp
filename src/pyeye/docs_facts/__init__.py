"""Documentation built on facts (#818, #824).

The code is the source of truth for every reference fact the docs state: tool
names and parameters, edges, environment variables, entry points and CI values.
This package extracts those facts and binds them into the docs, so a code change
that invalidates a documented fact fails CI in the same PR.

- :mod:`.facts`: the :class:`~.facts.Fact` and :class:`~.facts.View` types.
- :mod:`.extractors`: one extractor per fact family.
- :mod:`.registry`: :data:`~.registry.EXTRACTORS`, the one list of extractors.
- :mod:`.docs`: :class:`~.docs.DocEntry`; a repository's one list of documentation
  files is its config's ``docs`` (pyeye's: ``docs/facts/docs.toml``, #1107).
- :mod:`.binding`: the ``<!-- fact:begin ID -->`` marker blocks.
- :mod:`.pages`: the fully generated ``docs/reference/`` pages.
- :mod:`.cli`: ``generate`` and ``check`` (``scripts/docs_facts.py``).
"""
