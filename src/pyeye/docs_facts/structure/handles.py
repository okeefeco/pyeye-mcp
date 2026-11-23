"""Which handles an architecture page names, and whether the dump knows them (#1176).

The ``architecture-handles`` rule's logic (ruling B on #1173). A handle is
checked in two steps, and is stale only if both fail:

1. **The dump, a fast path.** It resolves when the ``structure`` kind's
   ``<prefix>.members.<owner>`` facts define it: an owner (a module or a
   class, nested ones included) or ``<owner>.<member>`` for one of its
   members, readable or not.
2. **pyeye's resolver** (the maintainer's direction on #1176: dogfood pyeye).
   A handle the dump doesn't list goes through pyeye's ``resolve`` on the
   page's repository (:func:`pyeye.decision_sites.pyeye_resolver`, the
   resolver ``decisions check`` uses), so a re-exported path (``pkg.Helper``
   for ``pkg.helpers.Helper``) resolves to its definition site like any other
   pyeye lookup. Only a handle it can't pin to one project definition is
   reported, with its reason (``unresolved``, ``ambiguous``, ``external``).

Both are static: the code is never imported or run (C19).

**The handle convention.** A handle is a dotted name whose first segment is a
top-level name the dump knows, with at least one more segment, such as
``pkg.mod.Name`` or ``pkg.mod.Cls.method``. It is found the same way in code
spans (the preferred form) and in plain prose: in both, ``pkg.mod.Name`` must
resolve. A name glued to a ``/``, ``.``, ``-`` or a word character on its left,
or to a ``/``, ``-`` or word character on its right, is part of something else
(``src/pkg/mod.py``, a URL, ``my-pkg.x``) and isn't a handle. Fact-block
content is blanked before the scan. Calls (``pkg.mod.f()``) are checked as
``pkg.mod.f``. A dotted name that isn't a handle but looks like one, such as a
file named ``pkg.lock``, is allowed per page with the page's ``allow`` entry.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from ...decision_sites import Resolver, pyeye_resolver
from ..facts import Fact


def known(prefix: str, facts: Mapping[str, Any]) -> frozenset[str]:
    """Every handle the *prefix* dump defines: each owner and each of its members."""
    head = f"{prefix}.members."
    found: set[str] = set()
    for fact_id, item in facts.items():
        if not fact_id.startswith(head) or not isinstance(item, Fact):
            continue
        owner = fact_id[len(head) :]
        found.add(owner)
        value = item.value if isinstance(item.value, Mapping) else {}
        for group in ("members", "unreadable"):
            for member in value.get(group, ()):
                name = member.get("name") if isinstance(member, Mapping) else None
                if isinstance(name, str):
                    found.add(f"{owner}.{name}")
    return frozenset(found)


def roots(handles: Iterable[str]) -> frozenset[str]:
    """The top-level names *handles* start with: what a page's handle must start with."""
    return frozenset(h.split(".", 1)[0] for h in handles)


def _pattern(top: Iterable[str]) -> re.Pattern[str]:
    names = "|".join(re.escape(r) for r in sorted(top, key=len, reverse=True))
    return re.compile(rf"(?<![\w./-])(?:{names})(?:\.[A-Za-z_]\w*)+(?![\w/-])")


def named(text: str, top: Iterable[str]) -> Iterator[tuple[int, str]]:
    """Each handle in *text* rooted at one of *top*, with its 1-based line."""
    top = list(top)
    if not top:
        return
    for match in _pattern(top).finditer(text):
        yield text.count("\n", 0, match.start()) + 1, match.group(0)


def is_architecture_page(name: str, patterns: Iterable[str]) -> bool:
    """Whether the registered page *name* matches one of the ``architecture_pages`` globs."""
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


def resolver(root: Path) -> Resolver:
    """The resolver for a dump miss (step 2): pyeye's, over the repository at *root*.

    The shared one ``decisions check`` uses (#1178). Built here, not in the
    extractor, because extractors import nothing of pyeye beyond
    ``pyeye.docs_facts`` (#1098, ``tests/test_docs_facts_static.py``).
    """
    return pyeye_resolver(root)


def unresolved(
    text: str, defined: frozenset[str], resolver: Resolver | None = None
) -> list[tuple[int, str, str | None]]:
    """Each handle *text* names that neither *defined* nor *resolver* finds.

    Each is ``(line, handle, reason)``: *reason* is the resolver's, or ``None``
    when there was no resolver to ask. *resolver* is asked once per distinct
    handle the dump doesn't hold, and only then; with none, the dump decides.
    """
    misses = [(line, h) for line, h in named(text, roots(defined)) if h not in defined]
    if resolver is None:
        return [(line, h, None) for line, h in misses]
    answers = {h: resolver.canonical(h) for h in dict.fromkeys(h for _line, h in misses)}
    return [(line, h, answers[h][1]) for line, h in misses if answers[h][0] is None]
