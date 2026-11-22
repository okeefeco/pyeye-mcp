"""Structural facts about any codebase, for architecture docs (RFC #1083 step 2, #1092).

The pieces, each usable on its own:

* :mod:`.dump`: what pyeye knows about every module (members, signatures,
  one-line docstrings, ``imported_by``, ``imports``), collected statically;
* :mod:`.coverage`: the definitions on disk against the dump, so a gap is
  reported, never silent;
* :mod:`.candidates`: "possibly the same job" pairs scored from names,
  docstrings and parameters. Candidates, never findings;
* :mod:`.relations`: relationship labels for a pair from pyeye's facts
  (``callees``, ``superclasses``, ``deprecation``);
* :mod:`.layering`: ``CHECK no-import: A -> B`` lines checked against ``imports``.

Ported from the RFC #1083 trial scripts (2026-11-22); each module names the
script it came from. Nothing here imports or runs the analysed code (ruling C19).
"""
