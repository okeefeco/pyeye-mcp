"""The one not-found response shape, for every primitive (#545, #626).

When a lookup misses, ``inspect`` / ``outline`` / ``expand`` / ``resolve`` /
``resolve_at`` all return::

    { "found":  False,
      <lookup-argument echo>,   # per operation, under its own parameter names
      "reason": str,            # from the operation's closed reason set
      "detail": str }           # actionable next step

The echo carries the operation's **lookup** arguments only (tuning arguments
such as ``max_depth`` or ``project_path`` are not echoed). ``handle`` appears
only when the input really is a handle: a path or identifier is never put in
``handle``, because agents feed that field straight back to ``inspect``.

=============  ========================  ===================================================
Operation      Echo keys                 Reasons (closed set)
=============  ========================  ===================================================
inspect        ``handle``                ``unresolved``
outline        ``handle``                ``unresolved``
expand         ``handle``, ``edge``      ``unresolved``
resolve        ``identifier``            ``unresolved``, ``file_not_found``,
                                         ``no_symbol_at_position``
resolve_at     ``file``, ``line``,       ``file_not_found``, ``no_symbol_at_position``,
               ``column``                ``unresolved``
=============  ========================  ===================================================

``trace`` has no top-level not-found: it reports unresolved roots in its
``unresolved_roots`` list. Every successful response carries ``found: True``,
so a consumer branches on ``found`` rather than on which keys are present.
Built in one place so the operations cannot drift apart. The response
linter's Check N mirrors this table independently.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: The reason for a lookup that did not resolve to a symbol.
NOT_FOUND_REASON = "unresolved"
#: resolve / resolve_at: the named file does not exist.
FILE_NOT_FOUND = "file_not_found"
#: resolve / resolve_at: the file exists, but no symbol sits at that position.
NO_SYMBOL_AT_POSITION = "no_symbol_at_position"


@dataclass(frozen=True)
class NotFoundSpec:
    """What one operation's not-found response may contain."""

    echo_keys: tuple[str, ...]
    reasons: frozenset[str]


_POSITION_REASONS = frozenset({NOT_FOUND_REASON, FILE_NOT_FOUND, NO_SYMBOL_AT_POSITION})

NOT_FOUND_SPEC: dict[str, NotFoundSpec] = {
    "inspect": NotFoundSpec(("handle",), frozenset({NOT_FOUND_REASON})),
    "outline": NotFoundSpec(("handle",), frozenset({NOT_FOUND_REASON})),
    "expand": NotFoundSpec(("handle", "edge"), frozenset({NOT_FOUND_REASON})),
    "resolve": NotFoundSpec(("identifier",), _POSITION_REASONS),
    "resolve_at": NotFoundSpec(("file", "line", "column"), _POSITION_REASONS),
}


def _leaf(text: str) -> str:
    return text.rsplit(".", 1)[-1]


def _default_detail(operation: str, echo: Mapping[str, Any], reason: str) -> str:
    """An actionable next step for *reason*, phrased for *operation*'s input."""
    if operation == "resolve_at":
        where = f"{echo['file']}:{echo['line']}:{echo['column']}"
        if reason == FILE_NOT_FOUND:
            return (
                f"File {echo['file']!r} does not exist. Pass a path that exists, "
                "absolute or relative to project_path."
            )
        if reason == NO_SYMBOL_AT_POSITION:
            return (
                f"No symbol at {where}. Point at a name: line is 1-based and column "
                "0-based. Or call resolve() with the symbol's name."
            )
        return (
            f"The symbol at {where} did not resolve to a canonical handle. "
            "Call resolve() with its dotted name."
        )
    if operation == "resolve":
        identifier = str(echo["identifier"])
        if reason == FILE_NOT_FOUND:
            return (
                f"The file in {identifier!r} does not exist. Pass a path that exists, "
                "absolute or relative to project_path."
            )
        if reason == NO_SYMBOL_AT_POSITION:
            return (
                f"No symbol on the line in {identifier!r}. Use resolve_at(file, line, "
                "column) to point at a name, or resolve() the name itself."
            )
        return (
            f"{identifier!r} did not resolve to a symbol. Check the spelling, or "
            f"call resolve({_leaf(identifier)!r}) with the bare name to search the "
            "whole project."
        )
    handle = str(echo["handle"])
    return (
        f"Handle {handle!r} did not resolve to a symbol. "
        f"Call resolve({_leaf(handle)!r}) to find its canonical handle."
    )


def not_found_for(
    operation: str,
    echo: Mapping[str, Any],
    reason: str = NOT_FOUND_REASON,
    detail: str | None = None,
) -> dict[str, Any]:
    """Build *operation*'s not-found response.

    Args:
        operation: One of :data:`NOT_FOUND_SPEC`'s keys.
        echo: The lookup arguments, keyed exactly by the operation's echo keys.
        reason: A reason from the operation's closed set.
        detail: An actionable next step. Defaults to a reason-specific one.

    Raises:
        ValueError: If *operation* is unknown, *echo*'s keys differ from the
            spec, or *reason* is outside the operation's set. That is a
            programming error, not a lookup miss, so it fails loudly here
            instead of emitting a shape the contract doesn't allow.
    """
    spec = NOT_FOUND_SPEC.get(operation)
    if spec is None:
        raise ValueError(f"no not-found shape for operation {operation!r}")
    if set(echo) != set(spec.echo_keys):
        raise ValueError(
            f"{operation} not-found echoes {sorted(spec.echo_keys)}, got {sorted(echo)}"
        )
    if reason not in spec.reasons:
        raise ValueError(
            f"{operation} not-found reason must be one of {sorted(spec.reasons)}, "
            f"got {reason!r}"
        )
    result: dict[str, Any] = {"found": False}
    result.update((key, echo[key]) for key in spec.echo_keys)
    result["reason"] = reason
    result["detail"] = detail if detail else _default_detail(operation, echo, reason)
    return result


def not_found(handle: str, *, edge: str | None = None) -> dict[str, Any]:
    """The not-found response for an unresolvable *handle* (inspect/outline/expand).

    A thin wrapper over :func:`not_found_for`: ``expand`` passes *edge*, and
    the others don't. ``detail`` points at ``resolve`` on the handle's last
    dotted segment, because an exact-path handle that misses usually has the
    right leaf under the wrong module path.
    """
    if edge is None:
        return not_found_for("inspect", {"handle": handle})
    return not_found_for("expand", {"handle": handle, "edge": edge})
