"""Imports one shallow stdlib module, for the trace-vs-expand test (#614).

``textwrap`` imports only ``re``, so ``trace(xpkg.text, ["imports"])`` reaches a
refused interior node (``textwrap``) without walking deep stdlib import chains.
``logging`` -> ``io``/``weakref`` drives Jedi ~1500 frames deep, which
overflows the C stack on Windows / CPython 3.11.
"""

import textwrap


def wrap(text: str) -> str:
    """Wrap *text*."""
    return textwrap.fill(text)
