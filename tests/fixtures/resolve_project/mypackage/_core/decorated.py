"""Decorated-method fixtures — the wrapper-signature-leak regression (#437).

``@functools.cache`` (and ``@functools.lru_cache`` without ``maxsize``) resolve
through typeshed to ``_lru_cache_wrapper``, so Jedi's ``get_signatures()`` leaks
``_lru_cache_wrapper(*args: Hashable, **kwargs: Hashable) -> _T_co`` instead of
the method's own signature.  ``_build_signature`` must reconstruct the real
signature from the source AST in that case.

This lives in its own module so the line-number-sensitive ``widgets.py`` layout
stays untouched.

Canonical handles:
- mypackage._core.decorated.Cached.cached_method  (decorated — leaks via Jedi)
- mypackage._core.decorated.Cached.plain_method    (undecorated — control)
"""

import functools


class Cached:
    """Holds a @functools.cache-decorated method and an undecorated control."""

    @functools.cache  # noqa: B019 — intentional: reproduces the #437 wrapper leak
    def cached_method(self, a: int, b: int = 2) -> int:
        """Decorated method — Jedi leaks the wrapper signature for this."""
        return a + b

    def plain_method(self, a: int, b: int = 2) -> int:
        """Undecorated control — renders its own signature already."""
        return a + b
