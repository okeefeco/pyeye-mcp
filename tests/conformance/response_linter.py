"""Conformance linter for PyEye resolve / resolve_at / inspect responses.

This module enforces two load-bearing contracts that protect the API from
regressing into content-layer violations or incorrect absence-vs-zero
semantics.

Check A — Layering principle
----------------------------
PyEye returns semantic pointers + structured facts.  Source content (code
bodies, snippets, inline text) must never appear in operation responses.
See: docs/superpowers/specs/ layering section and
     ~/.claude/projects/okeefeco/pyeye-mcp.md → feedback_pyeye_layering.md

Four smuggling vectors are detected:

A.1 Multi-line string  — any string field with > ``_MULTILINE_THRESHOLD``
    lines is rejected, EXCEPT fields in ``_MULTILINE_ALLOWLIST``.
A.2 Field-name pattern — keys matching ``body``, ``source``, ``code``,
    ``snippet``, ``text`` or containing ``_source``, ``_body``, ``_snippet``,
    ``_code``, ``_text`` are rejected regardless of value.
A.3 Default-value smuggling — ``parameters[].default`` strings that contain
    newlines or exceed ``_DEFAULT_MAX_CHARS`` are rejected.
A.4 Indented-block heuristic — string values containing patterns like
    ``    def ``, ``    class ``, etc. are rejected (except allowlisted fields).

Check B — Absence-vs-zero invariant
-------------------------------------
``edge_counts`` must obey strict typing:

B.1 Value types — every value must be a plain ``int`` (not bool, None, float, str).
B.2 Known keys — every key must be in ``KNOWN_EDGE_TYPES`` or match the plugin
    edge regex ``r'^\\w+@\\w+$'``.
B.3 Phase 4 cross-check — for ``inspect`` responses, measured edges must be
    present for the declared kind (can be 0, but cannot be absent).
B.4 Nullable optional fields — ``re_exports``, ``highlights``, ``tags``,
    ``properties`` may be absent or present-with-typed-value; present-with-None
    is invalid.

Usage
-----
::

    from tests.conformance.response_linter import lint_response

    lint_response(result, "inspect")  # raises ConformanceViolation on failure
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class ConformanceViolation(AssertionError):
    """Raised when a response from resolve / resolve_at / inspect violates the spec.

    The message includes:
    - The rule violated (A.1, A.2, etc.)
    - The location in the response (e.g. ``parameters[2].default``)
    - The violating value (truncated if huge)
    - A pointer to the relevant documentation

    Multiple violations are batched into a single raise so the caller sees
    all problems at once.
    """


# ---------------------------------------------------------------------------
# Check A constants
# ---------------------------------------------------------------------------

# A.1 — Lines threshold
_MULTILINE_THRESHOLD: int = 5

# A.1 / A.4 — Fields that may legitimately be long or contain code examples.
# ``docstring`` is the only allowlisted field: long docstrings are the symbol's
# own documentation and may include code examples.  Adding a new allowlist entry
# requires an explicit justification comment here.
_MULTILINE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "docstring",  # Symbol's own documentation; may be long and contain examples.
    }
)

# A.2 — Exact-match banned key names
_BANNED_EXACT_KEYS: frozenset[str] = frozenset({"body", "source", "code", "snippet", "text"})

# A.2 — Substring patterns in key names that indicate content leakage
_BANNED_KEY_SUBSTRINGS: tuple[str, ...] = ("_source", "_body", "_snippet", "_code", "_text")

# A.3 — Maximum length for a parameters[].default value string
_DEFAULT_MAX_CHARS: int = 80

# A.4 — Indented-block patterns (4-space indent) that smell of source code
_INDENTED_PATTERNS: tuple[str, ...] = (
    "    def ",
    "    class ",
    "    if ",
    "    for ",
    "    return ",
)

# Layering violation doc pointer
_LAYERING_DOC = (
    "See feedback_pyeye_layering.md: "
    "PyEye returns pointers + structured semantic facts; "
    "Read is the content layer. "
    "Snippets/bodies in responses are a violation."
)

# ---------------------------------------------------------------------------
# Check B constants
# ---------------------------------------------------------------------------

# B.2 — Full vocabulary of known edge type keys.
# Keys in this set are accepted.  Future edge types should be added here with
# a comment explaining the phase or spec reference.
KNOWN_EDGE_TYPES: frozenset[str] = frozenset(
    {
        # Phase 4 measured edges (current implementation):
        "members",
        "superclasses",
        "subclasses",
        "callers",
        "references",
        # Future edges per spec Edge Type Vocabulary:
        "callees",
        "read_by",
        "written_by",
        "passed_by",
        "decorated_by",
        "decorates",
        "imports",
        "imported_by",
        "enclosing_scope",
        "overrides",
        "overridden_by",
    }
)

# B.2 — Plugin edge pattern: e.g. "validators@pydantic"
_PLUGIN_EDGE_RE: re.Pattern[str] = re.compile(r"^\w+@\w+$")

# B.3 — Phase 4 measured edges per kind.
# Maps kind → frozenset of edge keys that MUST be present (possibly 0) when
# the implementation measured them.  "other" kinds produce no measurements.
_PHASE4_EXPECTED_EDGES: dict[str, frozenset[str]] = {
    "class": frozenset({"members", "superclasses", "subclasses", "callers", "references"}),
    "module": frozenset({"members", "references"}),
    "function": frozenset({"callers", "references"}),
    "method": frozenset({"callers", "references"}),
    "attribute": frozenset({"references"}),
    "property": frozenset({"references"}),
    "variable": frozenset({"references"}),
}

# B.3 — Keys that must NOT appear (they are Phase 4 unmeasured edges).
# These are in KNOWN_EDGE_TYPES (future vocab) but are NOT measured by Phase 4.
# Their presence with any value (including 0) is a false claim about measurements.
_PHASE4_UNMEASURED_EDGES: frozenset[str] = frozenset(
    {
        "callees",
        "read_by",
        "written_by",
        "passed_by",
        "decorated_by",
        "decorates",
        "imports",
        "imported_by",
        "enclosing_scope",
        "overrides",
        "overridden_by",
    }
)

# B.4 — Optional fields that may not have a null value.
_NULLABLE_FORBIDDEN_FIELDS: tuple[str, ...] = ("re_exports", "highlights", "tags", "properties")

# ---------------------------------------------------------------------------
# Internal traversal helpers
# ---------------------------------------------------------------------------


def _walk(obj: Any, path: str) -> Iterator[tuple[str, str, Any]]:
    """Recursively yield (field_name, full_path, value) for all scalar leaves.

    Yields the immediate key + its value at each level so callers can check
    both key names (Check A.2) and string values (Check A.1, A.4).

    Args:
        obj: The object to walk (dict, list, or scalar).
        path: Current path string for error messages (e.g. ``"parameters[0]"``).

    Yields:
        ``(field_name, full_path, value)`` tuples.  For list elements,
        ``field_name`` is the parent list key; ``full_path`` includes the index.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            child_path = f"{path}.{key}" if path else key
            yield key, child_path, value
            if isinstance(value, (dict, list)):
                yield from _walk(value, child_path)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            child_path = f"{path}[{idx}]"
            if isinstance(item, (dict, list)):
                yield from _walk(item, child_path)
            # scalar list items are not yielded here (callers handle lists directly)


def _truncate(value: Any, max_len: int = 120) -> str:
    """Truncate a value repr for inclusion in error messages."""
    r = repr(value)
    if len(r) > max_len:
        return r[:max_len] + "…"
    return r


# ---------------------------------------------------------------------------
# Check A helpers
# ---------------------------------------------------------------------------


def _check_a1_multiline(
    field_name: str,
    path: str,
    value: Any,
    violations: list[str],
) -> None:
    """A.1 — Reject string values with more than _MULTILINE_THRESHOLD lines.

    Args:
        field_name: The immediate dict key for this value.
        path: Full path string in the response for error messages.
        value: The field value to check.
        violations: Mutable list to append violation messages to.
    """
    if not isinstance(value, str):
        return
    if field_name in _MULTILINE_ALLOWLIST:
        return
    line_count = value.count("\n") + 1
    if line_count > _MULTILINE_THRESHOLD:
        violations.append(
            f"[A.1 multi-line string] {path!r}: string has {line_count} lines "
            f"(threshold={_MULTILINE_THRESHOLD}); value={_truncate(value)}. "
            f"Add to _MULTILINE_ALLOWLIST with justification if this is intentional. "
            f"{_LAYERING_DOC}"
        )


def _check_a2_field_name(field_name: str, path: str, violations: list[str]) -> None:
    """A.2 — Reject any dict key whose name indicates content leakage.

    Rejects exact matches and substring matches independently of value.

    Args:
        field_name: The dict key to check.
        path: Full path string for error messages.
        violations: Mutable list to append violation messages to.
    """
    if field_name in _BANNED_EXACT_KEYS:
        violations.append(
            f"[A.2 field-name pattern] Key {field_name!r} at {path!r} is banned. "
            f"The names {sorted(_BANNED_EXACT_KEYS)} must never appear in operation responses "
            f"regardless of value — they signal source-content fields. "
            f"{_LAYERING_DOC}"
        )
        return
    for sub in _BANNED_KEY_SUBSTRINGS:
        if sub in field_name:
            violations.append(
                f"[A.2 field-name pattern] Key {field_name!r} at {path!r} contains "
                f"banned substring {sub!r}. "
                f"Keys containing {list(_BANNED_KEY_SUBSTRINGS)} signal content leakage. "
                f"{_LAYERING_DOC}"
            )
            return


def _check_a3_default_smuggling(
    response: dict[str, Any],
    violations: list[str],
) -> None:
    """A.3 — Reject complex defaults in parameters[].default fields.

    Checks only the ``parameters`` list at the top level of the response
    (function/method nodes).  Nested ``parameters`` in sub-dicts are not
    checked — the spec note applies to the operation's own parameter list.

    Args:
        response: The full response dict.
        violations: Mutable list to append violation messages to.
    """
    params = response.get("parameters")
    if not isinstance(params, list):
        return
    for idx, param in enumerate(params):
        if not isinstance(param, dict):
            continue
        default = param.get("default")
        if default is None:
            continue
        if not isinstance(default, str):
            continue
        path = f"parameters[{idx}].default"
        if "\n" in default:
            violations.append(
                f"[A.3 default-value smuggling] {path!r}: default contains newline(s); "
                f"value={_truncate(default)}. "
                f"Complex defaults must be omitted; use source pointers instead. "
                f"{_LAYERING_DOC}"
            )
        elif len(default) > _DEFAULT_MAX_CHARS:
            violations.append(
                f"[A.3 default-value smuggling] {path!r}: default has {len(default)} chars "
                f"(max={_DEFAULT_MAX_CHARS}); value={_truncate(default)}. "
                f"Complex defaults must be omitted; use source pointers instead. "
                f"{_LAYERING_DOC}"
            )


def _check_a4_indented_block(
    field_name: str,
    path: str,
    value: Any,
    violations: list[str],
) -> None:
    """A.4 — Reject string values containing indented code block patterns.

    Args:
        field_name: The immediate dict key for this value.
        path: Full path string for error messages.
        value: The field value to check.
        violations: Mutable list to append violation messages to.
    """
    if not isinstance(value, str):
        return
    if field_name in _MULTILINE_ALLOWLIST:
        return
    for pattern in _INDENTED_PATTERNS:
        if pattern in value:
            violations.append(
                f"[A.4 indented-block heuristic] {path!r}: string contains "
                f"indented-code pattern {pattern!r}; value={_truncate(value)}. "
                f"This looks like source code rendered as a string. "
                f"{_LAYERING_DOC}"
            )
            return  # one violation per field is enough


def _check_layering(response: dict[str, Any], operation: str, violations: list[str]) -> None:
    """Run all Check-A layering sub-checks, appending violations to the list.

    Args:
        response: The operation response dict.
        operation: Operation name (reserved for future operation-specific rules).
        violations: Mutable list to append violations to.
    """
    _ = operation  # Reserved for future operation-specific layering rules
    # Walk the full response to check A.1, A.2, A.4 recursively
    for field_name, path, value in _walk(response, ""):
        _check_a2_field_name(field_name, path, violations)
        _check_a1_multiline(field_name, path, value, violations)
        _check_a4_indented_block(field_name, path, value, violations)

    # A.3 is checked separately because it targets a specific structure
    _check_a3_default_smuggling(response, violations)


# ---------------------------------------------------------------------------
# Check B helpers
# ---------------------------------------------------------------------------


def _check_b1_edge_value_types(
    edge_counts: dict[str, Any],
    violations: list[str],
) -> None:
    """B.1 — Every value in edge_counts must be a plain int (not bool, None, float, str).

    Note: in Python, ``bool`` is a subclass of ``int``, so ``isinstance(True, int)``
    is ``True``.  We explicitly reject booleans first.

    Args:
        edge_counts: The ``edge_counts`` dict from the response.
        violations: Mutable list to append violation messages to.
    """
    for key, value in edge_counts.items():
        if type(value) is bool:  # explicit type() check to catch bool before int
            violations.append(
                f"[B.1 edge_counts value type] edge_counts[{key!r}] has value {value!r} "
                f"(bool); must be a plain int. "
                f"Use 0 for zero counts; absence means 'not measured'."
            )
        elif not isinstance(value, int):
            violations.append(
                f"[B.1 edge_counts value type] edge_counts[{key!r}] has value {value!r} "
                f"(type={type(value).__name__!r}); must be an integer. "
                f"Null/float/str values are not valid — "
                f"use absence (omit the key) to signal 'not measured'."
            )


def _check_b2_known_keys(
    edge_counts: dict[str, Any],
    violations: list[str],
) -> None:
    """B.2 — Every key in edge_counts must be in KNOWN_EDGE_TYPES or a plugin edge.

    Plugin edges match the pattern ``word@word`` (e.g. ``validators@pydantic``).

    Args:
        edge_counts: The ``edge_counts`` dict from the response.
        violations: Mutable list to append violation messages to.
    """
    for key in edge_counts:
        if key not in KNOWN_EDGE_TYPES and not _PLUGIN_EDGE_RE.match(key):
            violations.append(
                f"[B.2 unknown edge key] edge_counts[{key!r}] is unknown. "
                f"Known edge types: {sorted(KNOWN_EDGE_TYPES)}. "
                f"Plugin edges must match pattern 'word@plugin'. "
                f"Add new edge types to KNOWN_EDGE_TYPES in response_linter.py with justification."
            )


def _check_b3_phase4_cross_check(
    edge_counts: dict[str, Any],
    kind: str,
    violations: list[str],
) -> None:
    """B.3 — Cross-check that Phase 4 measured edges are present for the declared kind.

    Checks two things:
    1. For the declared kind, the expected Phase 4 edges must be present
       (possibly with value 0 — absence means "not measured").
    2. Edges from _PHASE4_UNMEASURED_EDGES must NOT appear (false claim of measurement).

    Only applies to ``inspect`` responses (resolve/resolve_at don't have edge_counts).

    Args:
        edge_counts: The ``edge_counts`` dict.
        kind: The ``kind`` field of the response.
        violations: Mutable list to append violation messages to.
    """
    # Check 1: expected edges must be present
    expected = _PHASE4_EXPECTED_EDGES.get(kind, frozenset())
    for edge in expected:
        if edge not in edge_counts:
            violations.append(
                f"[B.3 Phase 4 cross-check] edge_counts is missing {edge!r} "
                f"for kind={kind!r}. "
                f"Phase 4 measures {sorted(expected)} for {kind!r} handles. "
                f"Present-with-0 means measured-and-zero; absent means not measured. "
                f"If an edge timed out, it should be absent — but if the measurement "
                f"succeeded, even 0 must appear."
            )

    # Check 2: unmeasured edges must not appear
    for edge in _PHASE4_UNMEASURED_EDGES:
        if edge in edge_counts:
            violations.append(
                f"[B.3 Phase 4 cross-check] edge_counts[{edge!r}] is present but "
                f"{edge!r} is not measured by Phase 4. "
                f"This is a false claim about what was measured. "
                f"Remove the key, or add measurement logic to inspect.py "
                f"and update KNOWN_EDGE_TYPES / _PHASE4_UNMEASURED_EDGES accordingly."
            )


def _check_b4_nullable_optional_fields(
    response: dict[str, Any],
    violations: list[str],
) -> None:
    """B.4 — Optional fields may not have a null (None) value.

    Present-but-empty (``[]``, ``{}``) is valid.  Present-with-None is invalid
    because None is ambiguous between "absent" and "measured-but-empty".

    Args:
        response: The operation response dict.
        violations: Mutable list to append violation messages to.
    """
    for field in _NULLABLE_FORBIDDEN_FIELDS:
        if field in response and response[field] is None:
            violations.append(
                f"[B.4 nullable optional field] {field!r} is present with value None. "
                f"Use ABSENCE (omit the key) to signal 'not measured', "
                f"or present-with-typed-value ([], {{}}) to signal 'measured'. "
                f"None is ambiguous and forbidden."
            )


def _check_absence_vs_zero(
    response: dict[str, Any],
    operation: str,
    violations: list[str],
) -> None:
    """Run all Check-B absence-vs-zero sub-checks, appending violations to the list.

    Only ``inspect`` responses have ``edge_counts``; for ``resolve``/``resolve_at``
    only B.4 is checked (they don't have edge_counts by spec).

    Args:
        response: The operation response dict.
        operation: Operation name — only ``"inspect"`` gets B.1–B.3.
        violations: Mutable list to append violations to.
    """
    # B.4 applies to all operations
    _check_b4_nullable_optional_fields(response, violations)

    # B.1–B.3 only when edge_counts is present (inspect responses)
    edge_counts = response.get("edge_counts")
    if edge_counts is None:
        return
    if not isinstance(edge_counts, dict):
        violations.append(
            f"[B.1 edge_counts type] edge_counts must be a dict; "
            f"got {type(edge_counts).__name__!r}."
        )
        return

    _check_b1_edge_value_types(edge_counts, violations)
    _check_b2_known_keys(edge_counts, violations)

    if operation == "inspect":
        kind = response.get("kind", "")
        if isinstance(kind, str):
            _check_b3_phase4_cross_check(edge_counts, kind, violations)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def lint_response(response: dict[str, Any], operation: str) -> None:
    """Run all conformance checks against a single operation response.

    Accumulates ALL violations before raising so the caller sees every problem
    at once.  The linter is pure (no I/O, no analyzer instantiation).

    Args:
        response: The dict returned by resolve / resolve_at / inspect.
        operation: One of ``"resolve"``, ``"resolve_at"``, ``"inspect"`` —
            used in error messages and for operation-specific contract checks
            (e.g. ``inspect`` gets B.3 Phase 4 cross-check; others don't).

    Raises:
        ConformanceViolation: With a batched message listing every rule
            violated, the location in the response, the violating value
            (truncated), and a pointer to the relevant documentation.
    """
    violations: list[str] = []
    _check_layering(response, operation, violations)
    _check_absence_vs_zero(response, operation, violations)

    if violations:
        header = (
            f"ConformanceViolation: {len(violations)} rule(s) violated "
            f"in {operation!r} response:\n"
        )
        body = "\n\n".join(f"  [{i + 1}] {v}" for i, v in enumerate(violations))
        raise ConformanceViolation(header + body)
