"""Conformance linter for PyEye resolve / resolve_at / inspect / expand responses.

This module enforces two load-bearing contracts that protect the API from
regressing into content-layer violations or incorrect absence-vs-zero
semantics.  It also enforces structural-floor checks for ``expand`` responses
(ExpandResult discriminated union) and standalone ``Stub`` objects.

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
    Exception: ``source`` at the TOP LEVEL of an ``expand`` response is a
    canonical handle pointer (not content) and is exempt.  Any ``source`` key
    nested inside a Stub or sub-dict is still rejected.
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

Check E — ExpandResult structural floors (operation == "expand")
----------------------------------------------------------------
E.1 Required fields — ``source`` (str) and ``edge`` (str) must be present.
E.2 Discriminated-union exclusivity — exactly one of supported (has ``stubs``
    list) or unsupported (has ``unsupported: True``) branch; garbled/blended
    results are rejected.  The unsupported branch requires ``reason`` ∈
    {``deferred_reference_backend``, ``not_yet_implemented``, ``unknown_edge``}
    and a non-empty ``detail`` str.
E.3 ``unresolved_call_sites`` placement — only allowed on the supported branch
    when ``edge == "callees"``; must be a plain ``int`` (not bool).
E.4 Each Stub in ``stubs`` passes the Stub structural floor (S.*) and the
    layering check (A.*).

Check S — Stub structural floors (operation == "stub", or via E.4)
------------------------------------------------------------------
S.1 Required keys with correct types: ``handle`` (str), ``kind`` (str),
    ``scope`` ∈ {``project``, ``external``}, ``line_start`` (int, not bool),
    ``line_end`` (int, not bool, >= line_start).
S.2 ``signature`` is optional; when present it must be a single-line str
    (no ``\\n`` characters).
S.3 No source-content keys (reuses A.2 / A.1 / A.4 layering checks).

Usage
-----
::

    from tests.conformance.response_linter import lint_response

    lint_response(result, "inspect")  # raises ConformanceViolation on failure
    lint_response(result, "expand")   # raises ConformanceViolation on failure
    lint_response(stub,   "stub")     # raises ConformanceViolation on failure
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

# A.2 — Top-level keys that are EXEMPT from the banned-key check for specific
# operations.  The ``source`` field at the top level of an ``expand`` response
# is a canonical handle pointer (not source content); it is whitelisted there
# only.  Any ``source`` key nested inside a sub-dict or list item is still
# rejected.
#
# Mapping: operation_name → frozenset of top-level key names that are exempt.
_BANNED_KEY_TOP_LEVEL_EXEMPTIONS: dict[str, frozenset[str]] = {
    "expand": frozenset({"source"}),
}

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

# B.3 — Measured edges per kind.
# Maps kind → frozenset of edge keys that MUST be present (possibly 0) when
# the implementation measured them.  "other" kinds produce no measurements.
#
# ``callers`` and ``references`` were REMOVED from every kind (see #332): they
# were derived from Jedi's budget-capped ``get_references`` and under-reported
# non-deterministically, so they are no longer measured and now live in
# ``_PHASE4_UNMEASURED_EDGES`` (forbidden).  function/method/attribute/property/
# variable handles therefore have NO required edges — an empty edge_counts is
# valid for them.  They return once an indexed backend lands (#333).
_PHASE4_EXPECTED_EDGES: dict[str, frozenset[str]] = {
    "class": frozenset({"members", "superclasses", "subclasses"}),
    "module": frozenset({"members"}),
}

# B.3 — Keys that must NOT appear (unmeasured edges).
# These are in KNOWN_EDGE_TYPES (future vocab) but are NOT measured.
# Their presence with any value (including 0) is a false claim about measurements.
# ``callers``/``references`` are here pending the indexed-backend fix (#332/#333).
_PHASE4_UNMEASURED_EDGES: frozenset[str] = frozenset(
    {
        "callers",
        "references",
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


def _check_a2_field_name(
    field_name: str,
    path: str,
    violations: list[str],
    exempt_keys: frozenset[str] = frozenset(),
) -> None:
    """A.2 — Reject any dict key whose name indicates content leakage.

    Rejects exact matches and substring matches independently of value.

    Args:
        field_name: The dict key to check.
        path: Full path string for error messages.
        violations: Mutable list to append violation messages to.
        exempt_keys: A frozenset of key names that are exempt from the exact-match
            ban for this particular check (used for top-level expand fields like
            ``source`` which is a handle pointer, not content).
    """
    if field_name in exempt_keys:
        return
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

    For ``expand`` responses, the top-level ``source`` key is exempt from the
    A.2 exact-match ban because it carries a canonical handle pointer (not
    content).  Any ``source`` key nested inside a sub-dict is still checked.

    Args:
        response: The operation response dict.
        operation: Operation name — used to apply operation-specific exemptions.
        violations: Mutable list to append violations to.
    """
    top_level_exempt = _BANNED_KEY_TOP_LEVEL_EXEMPTIONS.get(operation, frozenset())

    # Walk the full response to check A.1, A.2, A.4 recursively.
    # For top-level keys, apply the operation-specific exemptions; for nested
    # keys (path contains '.'), no exemptions apply.
    for field_name, path, value in _walk(response, ""):
        # Apply exemptions only at the exact top level (path == field_name).
        exempt = top_level_exempt if path == field_name else frozenset()
        _check_a2_field_name(field_name, path, violations, exempt_keys=exempt)
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
# Check E + S constants
# ---------------------------------------------------------------------------

# E.2 — Valid reason values for the unsupported branch of ExpandResult.
_VALID_UNSUPPORTED_REASONS: frozenset[str] = frozenset(
    {
        "deferred_reference_backend",
        "not_yet_implemented",
        "unknown_edge",
    }
)

# S.1 — Valid scope values for a Stub.
_VALID_STUB_SCOPES: frozenset[str] = frozenset({"project", "external"})

# ---------------------------------------------------------------------------
# Check S — Stub structural-floor helpers
# ---------------------------------------------------------------------------


def _check_stub_structural_floor(
    stub: Any,
    path: str,
    violations: list[str],
) -> None:
    """S.1 + S.2 — Validate the structural floor of a Stub dict.

    Does NOT run layering checks (A.*) — those are handled by
    ``_check_layering`` via the recursive walk.  This function only verifies
    the required fields and their types.

    S.1 Required keys with correct types:
        - ``handle``     : str
        - ``kind``       : str
        - ``scope``      : str ∈ {``project``, ``external``}
        - ``line_start`` : int (not bool)
        - ``line_end``   : int (not bool), >= ``line_start``

    S.2 Optional ``signature``:
        - When present: must be a str with no ``\\n`` characters (single-line).

    Args:
        stub: The candidate Stub value (should be a dict).
        path: Path prefix for error messages (e.g. ``"stubs[0]"``).
        violations: Mutable list to append violation messages to.
    """
    if not isinstance(stub, dict):
        violations.append(
            f"[S.1 stub type] {path!r}: expected a dict; got {type(stub).__name__!r}."
        )
        return

    # S.1 — handle: required str
    handle = stub.get("handle")
    if "handle" not in stub:
        violations.append(f"[S.1 stub required key] {path!r}: missing required key 'handle'.")
    elif not isinstance(handle, str):
        violations.append(
            f"[S.1 stub field type] {path}.handle: expected str; "
            f"got {type(handle).__name__!r} ({_truncate(handle)})."
        )

    # S.1 — kind: required str
    kind = stub.get("kind")
    if "kind" not in stub:
        violations.append(f"[S.1 stub required key] {path!r}: missing required key 'kind'.")
    elif not isinstance(kind, str):
        violations.append(
            f"[S.1 stub field type] {path}.kind: expected str; "
            f"got {type(kind).__name__!r} ({_truncate(kind)})."
        )

    # S.1 — scope: required str ∈ {project, external}
    scope = stub.get("scope")
    if "scope" not in stub:
        violations.append(f"[S.1 stub required key] {path!r}: missing required key 'scope'.")
    elif not isinstance(scope, str):
        violations.append(
            f"[S.1 stub field type] {path}.scope: expected str ∈ "
            f"{sorted(_VALID_STUB_SCOPES)}; "
            f"got {type(scope).__name__!r} ({_truncate(scope)})."
        )
    elif scope not in _VALID_STUB_SCOPES:
        violations.append(
            f"[S.1 stub field value] {path}.scope: value {scope!r} is not valid; "
            f"must be one of {sorted(_VALID_STUB_SCOPES)}."
        )

    # S.1 — line_start: required int (not bool)
    line_start = stub.get("line_start")
    if "line_start" not in stub:
        violations.append(f"[S.1 stub required key] {path!r}: missing required key 'line_start'.")
    elif type(line_start) is bool:
        violations.append(
            f"[S.1 stub field type] {path}.line_start: expected int (not bool); "
            f"got bool ({_truncate(line_start)})."
        )
    elif not isinstance(line_start, int):
        violations.append(
            f"[S.1 stub field type] {path}.line_start: expected int; "
            f"got {type(line_start).__name__!r} ({_truncate(line_start)})."
        )

    # S.1 — line_end: required int (not bool), >= line_start
    line_end = stub.get("line_end")
    if "line_end" not in stub:
        violations.append(f"[S.1 stub required key] {path!r}: missing required key 'line_end'.")
    elif type(line_end) is bool:
        violations.append(
            f"[S.1 stub field type] {path}.line_end: expected int (not bool); "
            f"got bool ({_truncate(line_end)})."
        )
    elif not isinstance(line_end, int):
        violations.append(
            f"[S.1 stub field type] {path}.line_end: expected int; "
            f"got {type(line_end).__name__!r} ({_truncate(line_end)})."
        )
    else:
        # Only check ordering when both are valid ints (not bool)
        if (
            "line_start" in stub
            and isinstance(line_start, int)
            and type(line_start) is not bool
            and line_end < line_start
        ):
            violations.append(
                f"[S.1 stub field value] {path}: line_end ({line_end}) < "
                f"line_start ({line_start}); span must be non-negative."
            )

    # S.2 — signature: optional; when present must be a single-line str
    if "signature" in stub:
        sig = stub["signature"]
        if not isinstance(sig, str):
            violations.append(
                f"[S.2 stub signature type] {path}.signature: expected str; "
                f"got {type(sig).__name__!r} ({_truncate(sig)})."
            )
        elif "\n" in sig:
            violations.append(
                f"[S.2 stub signature single-line] {path}.signature: "
                f"signature must be a single-line str (no '\\n'); "
                f"value={_truncate(sig)}."
            )


# ---------------------------------------------------------------------------
# Check E — ExpandResult structural-floor helpers
# ---------------------------------------------------------------------------


def _check_expand_structural_floor(
    response: dict[str, Any],
    violations: list[str],
) -> None:
    """E.1–E.4 — Validate the structural floor of an ExpandResult dict.

    This function runs the structural checks only.  The layering check (A.*)
    is run separately by ``_check_layering`` which handles the top-level
    ``source`` exemption for ``expand`` responses.

    E.1 source (str) and edge (str) must be present.
    E.2 Exactly one of supported (has 'stubs' list) or unsupported
        (has 'unsupported': True) branch; blended/garbled results rejected.
    E.3 'unresolved_call_sites' only on supported branch when edge == 'callees';
        must be a plain int (not bool).
    E.4 Each Stub in stubs[] passes the Stub structural floor (S.*).

    Args:
        response: The ExpandResult dict.
        violations: Mutable list to append violation messages to.
    """
    # E.1 — source: required str
    source = response.get("source")
    if "source" not in response:
        violations.append(
            "[E.1 expand required field] 'source' is missing. "
            "ExpandResult must carry 'source' (canonical handle str) and 'edge' (str)."
        )
    elif not isinstance(source, str):
        violations.append(
            f"[E.1 expand field type] 'source' must be a str; "
            f"got {type(source).__name__!r} ({_truncate(source)})."
        )

    # E.1 — edge: required str
    edge_val = response.get("edge")
    if "edge" not in response:
        violations.append(
            "[E.1 expand required field] 'edge' is missing. "
            "ExpandResult must carry 'source' (canonical handle str) and 'edge' (str)."
        )
    elif not isinstance(edge_val, str):
        violations.append(
            f"[E.1 expand field type] 'edge' must be a str; "
            f"got {type(edge_val).__name__!r} ({_truncate(edge_val)})."
        )

    # E.2 — discriminated-union exclusivity
    has_stubs_key = "stubs" in response
    has_unsupported_key = "unsupported" in response
    stubs_val = response.get("stubs")
    unsupported_val = response.get("unsupported")

    if has_stubs_key and has_unsupported_key:
        # Key bleed: both branch discriminators present
        violations.append(
            "[E.2 expand union exclusivity] Both 'stubs' and 'unsupported' are present. "
            "ExpandResult is a discriminated union: exactly one branch must be used. "
            "A supported result must NOT carry 'unsupported'/'reason'; "
            "an unsupported result must NOT carry 'stubs'."
        )
        # Return early: further checks would be misleading for blended responses
        return

    if not has_stubs_key and not has_unsupported_key:
        # Garbled: neither branch
        violations.append(
            "[E.2 expand union exclusivity] Neither 'stubs' nor 'unsupported' is present. "
            "ExpandResult must carry exactly one branch: "
            "supported (has 'stubs' list) or unsupported (has 'unsupported': True)."
        )
        return

    if has_unsupported_key:
        # --- Unsupported branch ---
        if unsupported_val is not True:
            violations.append(
                f"[E.2 expand unsupported sentinel] 'unsupported' must be boolean True; "
                f"got {_truncate(unsupported_val)} (type={type(unsupported_val).__name__!r}). "
                f"The sentinel value must be exactly True, not a truthy or string equivalent."
            )

        # reason: required str ∈ _VALID_UNSUPPORTED_REASONS
        reason = response.get("reason")
        if "reason" not in response:
            violations.append(
                "[E.2 expand unsupported missing reason] 'reason' is missing on the "
                "unsupported branch. Must be one of "
                f"{sorted(_VALID_UNSUPPORTED_REASONS)}."
            )
        elif not isinstance(reason, str):
            violations.append(
                f"[E.2 expand unsupported reason type] 'reason' must be a str; "
                f"got {type(reason).__name__!r} ({_truncate(reason)})."
            )
        elif reason not in _VALID_UNSUPPORTED_REASONS:
            violations.append(
                f"[E.2 expand unsupported unknown reason] 'reason' value {reason!r} is not "
                f"a recognised reason. Must be one of {sorted(_VALID_UNSUPPORTED_REASONS)}."
            )

        # detail: required non-empty str
        detail = response.get("detail")
        if "detail" not in response:
            violations.append(
                "[E.2 expand unsupported missing detail] 'detail' is missing on the "
                "unsupported branch. Must be a non-empty str explaining the reason."
            )
        elif not isinstance(detail, str) or not detail:
            violations.append(
                f"[E.2 expand unsupported detail] 'detail' must be a non-empty str; "
                f"got {_truncate(detail)} (type={type(detail).__name__!r})."
            )

        # E.3 — unresolved_call_sites must NOT be present on the unsupported branch
        if "unresolved_call_sites" in response:
            violations.append(
                "[E.3 unresolved_call_sites placement] 'unresolved_call_sites' is present "
                "on the unsupported branch. It must only appear on the supported branch "
                "when edge == 'callees'."
            )

    else:
        # --- Supported branch (has_stubs_key) ---
        if not isinstance(stubs_val, list):
            violations.append(
                f"[E.2 expand stubs type] 'stubs' must be a list; "
                f"got {type(stubs_val).__name__!r} ({_truncate(stubs_val)}). "
                f"Use [] (empty list) to signal 'measured, none found'."
            )
            # Cannot check stub items if stubs is not a list
        else:
            # E.4 — each Stub passes the Stub structural floor
            for idx, stub in enumerate(stubs_val):
                _check_stub_structural_floor(stub, f"stubs[{idx}]", violations)

        # E.3 — unresolved_call_sites: if present, must be on callees, and be a plain int
        if "unresolved_call_sites" in response:
            ucs = response["unresolved_call_sites"]
            edge_is_callees = isinstance(edge_val, str) and edge_val == "callees"
            if not edge_is_callees:
                violations.append(
                    f"[E.3 unresolved_call_sites placement] 'unresolved_call_sites' is "
                    f"present but edge={edge_val!r} (not 'callees'). "
                    f"'unresolved_call_sites' is only valid on the supported branch "
                    f"when edge == 'callees'."
                )
            elif type(ucs) is bool:
                violations.append(
                    f"[E.3 unresolved_call_sites type] 'unresolved_call_sites' must be "
                    f"a plain int (not bool); got bool ({_truncate(ucs)})."
                )
            elif not isinstance(ucs, int):
                violations.append(
                    f"[E.3 unresolved_call_sites type] 'unresolved_call_sites' must be "
                    f"an int; got {type(ucs).__name__!r} ({_truncate(ucs)})."
                )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def lint_response(response: dict[str, Any], operation: str) -> None:
    """Run all conformance checks against a single operation response.

    Accumulates ALL violations before raising so the caller sees every problem
    at once.  The linter is pure (no I/O, no analyzer instantiation).

    Args:
        response: The dict returned by resolve / resolve_at / inspect / expand,
            or a standalone Stub dict.
        operation: One of ``"resolve"``, ``"resolve_at"``, ``"inspect"``,
            ``"expand"``, ``"stub"`` — used in error messages and for
            operation-specific contract checks:
            - ``inspect``  gets B.3 Phase 4 cross-check
            - ``expand``   gets E.1–E.4 structural-floor + top-level source exemption
            - ``stub``     gets S.1–S.2 structural-floor
            - others don't get operation-specific checks

    Raises:
        ConformanceViolation: With a batched message listing every rule
            violated, the location in the response, the violating value
            (truncated), and a pointer to the relevant documentation.
    """
    violations: list[str] = []
    _check_layering(response, operation, violations)

    if operation == "expand":
        _check_expand_structural_floor(response, violations)
    elif operation == "stub":
        _check_stub_structural_floor(response, "", violations)
    else:
        _check_absence_vs_zero(response, operation, violations)

    if violations:
        header = (
            f"ConformanceViolation: {len(violations)} rule(s) violated "
            f"in {operation!r} response:\n"
        )
        body = "\n\n".join(f"  [{i + 1}] {v}" for i, v in enumerate(violations))
        raise ConformanceViolation(header + body)
