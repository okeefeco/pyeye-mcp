"""Relationship labels for a candidate pair, from pyeye's facts only (#1092).

Ported from the RFC #1083 trial's ``scripts/calls.py`` and ``scripts/rules_v3.py``
(2026-11-22), with one change the trial's own results asked for: an
unconditional deprecation is a **flag** on its side, never a label. A label
removes a pair from the duplicate flags, and a deprecated copy is still a copy.

Labels, first match wins:

* ``delegates``: one side calls (or constructs) the other. pyeye ``callees``;
  a class's callees are the union over its methods.
* ``override``: same method name, and one owner class is a (transitive) project
  ancestor of the other. pyeye ``superclasses``.
* ``sibling``: both are methods of classes with a project ancestor in common.

A pair no rule labels is a ``possible duplicate (unverified)``. Nothing here
judges: a model verdict did worse than these rules in the trial. Property reads
aren't calls, so a wrapper that only reads a property isn't seen (#333).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .dump import Dump, Pyeye

DELEGATES = "delegates"
OVERRIDE = "override"
SIBLING = "sibling"
UNVERIFIED = "possible duplicate (unverified)"


class Facts(Protocol):
    """The pyeye facts the rules read. Each answers ``None`` when it can't measure."""

    def callees(self, handle: str) -> frozenset[str] | None:
        """The project callables *handle* calls."""

    def superclasses(self, handle: str) -> tuple[str, ...] | None:
        """*handle*'s direct project base classes."""

    def deprecation(self, handle: str) -> tuple[str, ...] | None:
        """The ``kind`` of each piece of deprecation evidence pyeye reports (#1082)."""


@dataclass(frozen=True)
class Relation:
    """One pair, labelled.

    Attributes:
        a: One side.
        b: The other side.
        label: A rule's label, or :data:`UNVERIFIED`.
        deprecated: The sides with an unconditional deprecation (a flag).
        conditionally_deprecated: The sides that warn only on some path.
        measured: Whether ``callees`` answered for both sides. When it didn't, a
            missing ``delegates`` label means "unknown", not "no call".
    """

    a: str
    b: str
    label: str
    deprecated: tuple[str, ...]
    conditionally_deprecated: tuple[str, ...]
    measured: bool


class PyeyeFacts:
    """:class:`Facts` from pyeye, cached per handle; classes read through the dump."""

    def __init__(self, ops: Pyeye, dump: Dump) -> None:
        """Read through *ops*; *dump* says which handles are classes and their methods."""
        self._ops = ops
        self._dump = dump
        self._callees: dict[str, frozenset[str] | None] = {}
        self._bases: dict[str, tuple[str, ...] | None] = {}
        self._deprecation: dict[str, tuple[str, ...] | None] = {}

    def _edge(self, handle: str, edge: str) -> list[dict[str, Any]] | None:
        result = self._ops.expand(handle, edge)
        if not result.get("found") or "stubs" not in result:
            return None
        return list(result["stubs"])

    def callees(self, handle: str) -> frozenset[str] | None:
        """The project callables *handle* calls; a class's are its methods' union."""
        if handle not in self._callees:
            self._callees[handle] = self._measure_callees(handle)
        return self._callees[handle]

    def _measure_callees(self, handle: str) -> frozenset[str] | None:
        definition = self._dump.by_handle.get(handle)
        if definition is not None and definition.kind == "class":
            methods = [
                d.handle for d in self._dump.definitions if d.owner == handle and d.kind == "method"
            ]
            if not methods:
                return None
            found: set[str] = set()
            for method in methods:
                found |= self.callees(method) or set()
            return frozenset(found)
        stubs = self._edge(handle, "callees")
        if stubs is None:
            return None
        return frozenset(s["handle"] for s in stubs if s.get("scope") == "project")

    def superclasses(self, handle: str) -> tuple[str, ...] | None:
        """*handle*'s direct project base classes, from ``superclasses``."""
        if handle not in self._bases:
            stubs = self._edge(handle, "superclasses")
            self._bases[handle] = (
                None
                if stubs is None
                else tuple(s["handle"] for s in stubs if s.get("scope") == "project")
            )
        return self._bases[handle]

    def deprecation(self, handle: str) -> tuple[str, ...] | None:
        """The kinds of deprecation evidence ``inspect`` reports for *handle* (#1082)."""
        if handle not in self._deprecation:
            node = self._ops.inspect(handle)
            evidence = node.get("deprecation") if node.get("found") else None
            self._deprecation[handle] = (
                None if evidence is None else tuple(str(e.get("kind", "")) for e in evidence)
            )
        return self._deprecation[handle]


def calls(callees: frozenset[str] | None, target: str) -> bool:
    """Whether *callees* holds *target* or something inside it (a method, a constructor)."""
    return bool(callees) and any(c == target or c.startswith(f"{target}.") for c in callees or ())


def ancestors(cls: str, facts: Facts) -> frozenset[str]:
    """Every project ancestor of *cls*, cycles tolerated."""
    seen: set[str] = set()
    todo = list(facts.superclasses(cls) or ())
    while todo:
        base = todo.pop()
        if base in seen or base == cls:
            continue
        seen.add(base)
        todo.extend(facts.superclasses(base) or ())
    return frozenset(seen)


def relate(a: str, b: str, facts: Facts, owner_class: Callable[[str], str | None]) -> Relation:
    """Label one pair.

    Args:
        a: One side.
        b: The other side.
        facts: pyeye's facts.
        owner_class: The class a handle is a method of, or ``None`` if it isn't one.
    """
    ca, cb = facts.callees(a), facts.callees(b)
    label = UNVERIFIED
    if calls(ca, b) or calls(cb, a):
        label = DELEGATES
    else:
        owner_a, owner_b = owner_class(a), owner_class(b)
        if owner_a and owner_b:
            up_a, up_b = ancestors(owner_a, facts), ancestors(owner_b, facts)
            if a.rsplit(".", 1)[-1] == b.rsplit(".", 1)[-1] and (
                owner_a in up_b or owner_b in up_a
            ):
                label = OVERRIDE
            elif up_a & up_b:
                label = SIBLING
    kinds = {h: facts.deprecation(h) or () for h in (a, b)}
    return Relation(
        a=a,
        b=b,
        label=label,
        deprecated=tuple(h for h in (a, b) if "unconditional" in kinds[h]),
        conditionally_deprecated=tuple(h for h in (a, b) if "conditional" in kinds[h]),
        measured=ca is not None and cb is not None,
    )


def owner_classes(dump: Dump) -> Callable[[str], str | None]:
    """The class each method in *dump* belongs to, as :func:`relate` wants it."""
    owners: Mapping[str, str] = {
        d.handle: d.owner
        for d in dump.definitions
        if d.kind == "method" and getattr(dump.by_handle.get(d.owner), "kind", "") == "class"
    }
    return owners.get


def relate_all(pairs: Iterable[tuple[str, str]], facts: Facts, dump: Dump) -> list[Relation]:
    """Label every pair, in order."""
    owner = owner_classes(dump)
    return [relate(a, b, facts, owner) for a, b in pairs]
