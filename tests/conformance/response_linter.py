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
E.1 Required fields — ``source`` (str, single-line) and ``edge`` (str, single-line)
    must be present.  Both are identifiers (handle / edge-name), not content — they
    must not contain newlines.
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

Check T — trace Subgraph structural floors (operation == "trace")
-----------------------------------------------------------------
T.1 Required keys with correct types: ``nodes`` (dict Map<Handle, Stub>),
    ``edges`` (list), ``truncated`` (bool, not truthy), ``unsupported_edges``
    (list).
T.2 Each node value passes the Stub floor (S.*); the node KEY equals the stub's
    ``handle`` (the dedup-by-handle invariant).
T.3 Each edge is ``{from, to, kind}`` of single-line strs.
T.4 Each ``unsupported_edges`` entry is ``{edge, reason, detail}`` with ``reason``
    ∈ the valid unsupported reasons and a non-empty ``detail`` (mirrors E.2).
T.5 ``truncation_reasons`` is a list of valid causes (``max_depth`` / ``max_nodes``)
    and is consistent with ``truncated`` (true iff the list is non-empty).

Check O — outline OutlineTree structural floors (operation == "outline")
------------------------------------------------------------------------
O.1 ``node`` is REQUIRED and passes the Stub structural floor (S.*).
O.2 ``truncated`` present ⇒ value is exactly ``true`` (absent-not-false contract),
    ``truncation_reason`` present and in the outline enum
    {``max_depth``, ``max_nodes``, ``external``}, and ``children`` ABSENT.
    ``truncated: false`` is rejected.  A truncated node carrying ``children``
    (even ``children: []``) is rejected (Contract 1 — absent ⇔ not expanded).
O.3 ``truncated`` absent ⇒ ``truncation_reason`` absent.
O.4 ``children`` present ⇒ it is a list (possibly empty) of OutlineTree; each
    item is validated recursively (applies the same O.* + A.* rules at every
    depth).

Note: Check A layering (no source content) is applied to the whole tree by
``_check_layering`` / ``_walk``, which already recurses into nested dicts and
lists.  No second traversal is needed in Check O — the existing walk reaches
``node`` Stubs and ``children`` items at any depth automatically.

Usage
-----
::

    from tests.conformance.response_linter import lint_response

    lint_response(result, "inspect")  # raises ConformanceViolation on failure
    lint_response(result, "expand")   # raises ConformanceViolation on failure
    lint_response(result, "trace")    # raises ConformanceViolation on failure
    lint_response(stub,   "stub")     # raises ConformanceViolation on failure
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any, TypeGuard

# ---------------------------------------------------------------------------
# Shared type helpers
# ---------------------------------------------------------------------------


def _is_plain_int(value: Any) -> TypeGuard[int]:
    """True if value is an int but NOT a bool (bool is an int subclass)."""
    return isinstance(value, int) and type(value) is not bool


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
        # Edges inspect measures in edge_counts (symbol-local, current impl):
        "members",
        "superclasses",
        # Known edges NOT measured by inspect (expand-only / deferred):
        "subclasses",  # expand-only — project-wide scan, no cheap preview (#392)
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
# Only edges derivable from the symbol's own definition are measured by inspect.
#
# ``subclasses`` was REMOVED from ``class`` (see #392): counting it requires the
# same project-wide inheritance scan as listing them, so it has no cheap-preview
# value and is now an expand-only edge.  It lives in ``_PHASE4_UNMEASURED_EDGES``
# (forbidden in inspect's edge_counts).
#
# ``callers`` and ``references`` were REMOVED from every kind (see #332): they
# were derived from Jedi's budget-capped ``get_references`` and under-reported
# non-deterministically, so they are no longer measured and now live in
# ``_PHASE4_UNMEASURED_EDGES`` (forbidden).  function/method/attribute/property/
# variable handles therefore have NO required edges — an empty edge_counts is
# valid for them.  They return once an indexed backend lands (#333).
_PHASE4_EXPECTED_EDGES: dict[str, frozenset[str]] = {
    "class": frozenset({"members", "superclasses"}),
    "module": frozenset({"members"}),
}

# B.3 — Keys that must NOT appear (unmeasured edges).
# These are in KNOWN_EDGE_TYPES (future vocab) but are NOT measured.
# Their presence with any value (including 0) is a false claim about measurements.
# ``subclasses`` is here because it is expand-only, not inspect-measured (#392).
# ``callers``/``references`` are here pending the indexed-backend fix (#332/#333).
_PHASE4_UNMEASURED_EDGES: frozenset[str] = frozenset(
    {
        "subclasses",
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
        if type(value) is bool:  # bool subclasses int; reject before the int check
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

# T.1 — Valid trace truncation-cause values.
# IMPORTANT: This is TRACE's enum only.  Do NOT extend it with "external" — that
# would silently loosen trace validation.  Outline uses a separate constant below.
_VALID_TRUNCATION_REASONS: frozenset[str] = frozenset({"max_depth", "max_nodes"})

# O.2 — Valid outline truncation_reason values (superset of trace's: adds "external").
# Outline's external cap fires when a subtree of an external node is not walked;
# trace never emits "external" as a per-node reason, so the two enums are kept apart.
_VALID_OUTLINE_TRUNCATION_REASONS: frozenset[str] = frozenset(
    {"max_depth", "max_nodes", "external"}
)

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
        if "line_start" in stub and _is_plain_int(line_start) and line_end < line_start:
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

    E.1 source (str, single-line) and edge (str, single-line) must be present.
    E.2 Exactly one of supported (has 'stubs' list) or unsupported
        (has 'unsupported': True) branch; blended/garbled results rejected.
    E.3 'unresolved_call_sites' only on supported branch when edge == 'callees';
        must be a plain int (not bool).
    E.4 Each Stub in stubs[] passes the Stub structural floor (S.*).

    Args:
        response: The ExpandResult dict.
        violations: Mutable list to append violation messages to.
    """
    # E.1 — source: required single-line str (canonical handle pointer)
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
    elif "\n" in source:
        violations.append(
            f"[E.1 expand field single-line] 'source' must be a single-line str "
            f"(canonical handle — no newlines); value={_truncate(source)}."
        )

    # E.1 — edge: required single-line str (edge name)
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
    elif "\n" in edge_val:
        violations.append(
            f"[E.1 expand field single-line] 'edge' must be a single-line str "
            f"(edge name — no newlines); value={_truncate(edge_val)}."
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
# Check T — trace Subgraph structural-floor helpers
# ---------------------------------------------------------------------------


def _check_trace_edge(edge: Any, path: str, violations: list[str]) -> None:
    """T.3 — Validate one Subgraph edge: ``{from, to, kind}`` single-line strs."""
    if not isinstance(edge, dict):
        violations.append(
            f"[T.3 trace edge type] {path}: expected a dict; got {type(edge).__name__!r}."
        )
        return
    for field in ("from", "to", "kind"):
        if field not in edge:
            violations.append(
                f"[T.3 trace edge required key] {path}: missing required key {field!r}."
            )
            continue
        value = edge[field]
        if not isinstance(value, str):
            violations.append(
                f"[T.3 trace edge field type] {path}.{field}: expected str; "
                f"got {type(value).__name__!r} ({_truncate(value)})."
            )
        elif "\n" in value:
            violations.append(
                f"[T.3 trace edge single-line] {path}.{field}: must be single-line; "
                f"value={_truncate(value)}."
            )


def _check_trace_unsupported_edge(item: Any, path: str, violations: list[str]) -> None:
    """T.4 — Validate one ``unsupported_edges`` entry: ``{edge, reason, detail}``.

    Mirrors the ExpandResult unsupported branch: ``reason`` must be one of
    :data:`_VALID_UNSUPPORTED_REASONS`, and ``detail`` must be a non-empty str.
    """
    if not isinstance(item, dict):
        violations.append(
            f"[T.4 trace unsupported_edge type] {path}: expected a dict; "
            f"got {type(item).__name__!r}."
        )
        return

    if "edge" not in item:
        violations.append(f"[T.4 trace unsupported_edge required key] {path}: missing 'edge'.")
    elif not isinstance(item["edge"], str):
        violations.append(
            f"[T.4 trace unsupported_edge field type] {path}.edge: expected str; "
            f"got {type(item['edge']).__name__!r}."
        )

    reason = item.get("reason")
    if "reason" not in item:
        violations.append(f"[T.4 trace unsupported_edge required key] {path}: missing 'reason'.")
    elif not isinstance(reason, str):
        violations.append(
            f"[T.4 trace unsupported_edge field type] {path}.reason: expected str; "
            f"got {type(reason).__name__!r}."
        )
    elif reason not in _VALID_UNSUPPORTED_REASONS:
        violations.append(
            f"[T.4 trace unsupported_edge unknown reason] {path}.reason: value {reason!r} "
            f"is not recognised; must be one of {sorted(_VALID_UNSUPPORTED_REASONS)}."
        )

    detail = item.get("detail")
    if "detail" not in item:
        violations.append(f"[T.4 trace unsupported_edge required key] {path}: missing 'detail'.")
    elif not isinstance(detail, str) or not detail:
        violations.append(
            f"[T.4 trace unsupported_edge detail] {path}.detail: must be a non-empty str; "
            f"got {_truncate(detail)} (type={type(detail).__name__!r})."
        )


def _check_trace_structural_floor(
    response: dict[str, Any],
    violations: list[str],
) -> None:
    """T.1–T.4 — Validate the structural floor of a trace ``Subgraph`` dict.

    Layering (A.*) is run separately by ``_check_layering``.

    T.1 ``nodes`` (dict), ``edges`` (list), ``truncated`` (bool, not truthy), and
        ``unsupported_edges`` (list) are present with correct types.
    T.2 Each node value passes the Stub floor (S.*), and the node KEY equals the
        stub's ``handle`` (the dedup-by-handle invariant).
    T.3 Each edge is ``{from, to, kind}`` of single-line strs.
    T.4 Each ``unsupported_edges`` entry is ``{edge, reason ∈ valid, detail}``.
    """
    # T.1 / T.2 — nodes
    nodes = response.get("nodes")
    if "nodes" not in response:
        violations.append(
            "[T.1 trace required key] 'nodes' is missing. A Subgraph must carry "
            "'nodes', 'edges', 'truncated', and 'unsupported_edges'."
        )
    elif not isinstance(nodes, dict):
        violations.append(
            f"[T.1 trace field type] 'nodes' must be a dict (Map<Handle, Stub>); "
            f"got {type(nodes).__name__!r}."
        )
    else:
        for key, stub in nodes.items():
            node_path = f"nodes[{key!r}]"
            if not isinstance(key, str):
                violations.append(
                    f"[T.2 trace node key] {node_path}: node key must be a str handle; "
                    f"got {type(key).__name__!r}."
                )
            _check_stub_structural_floor(stub, node_path, violations)
            if isinstance(key, str) and isinstance(stub, dict):
                handle = stub.get("handle")
                if isinstance(handle, str) and handle != key:
                    violations.append(
                        f"[T.2 trace node key/handle] {node_path}.handle is {handle!r}; "
                        "the node key must equal the stub handle (dedup-by-handle)."
                    )

    # T.1 / T.3 — edges
    edges = response.get("edges")
    if "edges" not in response:
        violations.append("[T.1 trace required key] 'edges' is missing.")
    elif not isinstance(edges, list):
        violations.append(
            f"[T.1 trace field type] 'edges' must be a list; got {type(edges).__name__!r}."
        )
    else:
        for idx, edge in enumerate(edges):
            _check_trace_edge(edge, f"edges[{idx}]", violations)

    # T.1 — truncated: required bool (exactly bool, not truthy)
    truncated = response.get("truncated")
    if "truncated" not in response:
        violations.append("[T.1 trace required key] 'truncated' is missing.")
    elif type(truncated) is not bool:
        violations.append(
            f"[T.1 trace field type] 'truncated' must be a bool; "
            f"got {type(truncated).__name__!r}."
        )

    # T.5 — truncation_reasons: required list of valid causes; must be consistent
    # with the derived ``truncated`` boolean (true iff reasons non-empty).
    reasons = response.get("truncation_reasons")
    if "truncation_reasons" not in response:
        violations.append(
            "[T.5 trace required key] 'truncation_reasons' is missing. It is [] when "
            "the trace terminated naturally, or lists the cap(s) that fired "
            f"({sorted(_VALID_TRUNCATION_REASONS)})."
        )
    elif not isinstance(reasons, list):
        violations.append(
            f"[T.5 trace field type] 'truncation_reasons' must be a list; "
            f"got {type(reasons).__name__!r}."
        )
    else:
        for idx, item in enumerate(reasons):
            if item not in _VALID_TRUNCATION_REASONS:
                violations.append(
                    f"[T.5 trace truncation_reasons value] truncation_reasons[{idx}]: "
                    f"value {item!r} is not recognised; must be one of "
                    f"{sorted(_VALID_TRUNCATION_REASONS)}."
                )
        # Consistency with the back-compat boolean.
        if type(truncated) is bool and truncated != bool(reasons):
            violations.append(
                f"[T.5 trace truncation consistency] 'truncated' is {truncated} but "
                f"'truncation_reasons' is {_truncate(reasons)}; 'truncated' must be "
                "true iff 'truncation_reasons' is non-empty."
            )

    # T.1 / T.4 — unsupported_edges
    unsupported = response.get("unsupported_edges")
    if "unsupported_edges" not in response:
        violations.append(
            "[T.1 trace required key] 'unsupported_edges' is missing. Use [] when every "
            "edge in 'follow' is supported."
        )
    elif not isinstance(unsupported, list):
        violations.append(
            f"[T.1 trace field type] 'unsupported_edges' must be a list; "
            f"got {type(unsupported).__name__!r}."
        )
    else:
        for idx, item in enumerate(unsupported):
            _check_trace_unsupported_edge(item, f"unsupported_edges[{idx}]", violations)


# ---------------------------------------------------------------------------
# Check O — OutlineTree structural-floor helpers
# ---------------------------------------------------------------------------


def _check_outline_tree_node(
    tree: Any,
    path: str,
    violations: list[str],
) -> None:
    """O.1–O.4 — Validate one OutlineTree node recursively.

    Layering (A.*) is run separately by ``_check_layering`` which already
    recurses into the whole response dict/list tree, so every ``node`` Stub
    and every ``children`` list item is covered automatically.

    O.1 ``node`` is REQUIRED and passes the Stub structural floor (S.*).
    O.2 ``truncated`` present ⇒ value is exactly ``True`` (not false, not a
        string), ``truncation_reason`` is present and in the outline enum,
        and ``children`` is ABSENT.  ``truncated: False`` is rejected.
    O.3 ``truncated`` absent ⇒ ``truncation_reason`` absent.
    O.4 ``children`` present ⇒ it is a list (possibly empty) of OutlineTree;
        each item is validated recursively.

    Args:
        tree: The candidate OutlineTree value (should be a dict).
        path: Path prefix for error messages (e.g. ``"children[0]"``).
        violations: Mutable list to append violation messages to.
    """
    if not isinstance(tree, dict):
        violations.append(
            f"[O.1 outline tree type] {path!r}: expected a dict (OutlineTree); "
            f"got {type(tree).__name__!r}."
        )
        return

    # O.1 — node: REQUIRED, must pass Stub structural floor
    if "node" not in tree:
        violations.append(
            f"[O.1 outline required key] {path!r}: missing required key 'node'. "
            "Every OutlineTree must carry a 'node' (Stub) identifying the scope."
        )
    else:
        _check_stub_structural_floor(tree["node"], f"{path}.node", violations)

    has_truncated = "truncated" in tree
    has_truncation_reason = "truncation_reason" in tree
    has_children = "children" in tree

    # O.2 — truncated: if present, must be exactly True (absent-not-false contract)
    if has_truncated:
        truncated_val = tree["truncated"]
        if truncated_val is False:
            violations.append(
                f"[O.2 outline truncated absent-not-false] {path}.truncated: "
                "value is False, which is forbidden. "
                "The absence-not-false contract requires fully-walked nodes to OMIT "
                "'truncated' entirely — never set it to false. "
                "See spec §4.2: truncated is present ONLY on cut-off nodes."
            )
        elif truncated_val is not True:
            violations.append(
                f"[O.2 outline truncated type] {path}.truncated: "
                f"value must be exactly True (boolean); got {_truncate(truncated_val)} "
                f"(type={type(truncated_val).__name__!r})."
            )
        else:
            # truncated is True — validate co-occurring fields
            if not has_truncation_reason:
                violations.append(
                    f"[O.2 outline truncated co-occurrence] {path}: "
                    "'truncated': true requires 'truncation_reason' to be present. "
                    f"Valid reasons: {sorted(_VALID_OUTLINE_TRUNCATION_REASONS)}."
                )
            if has_children:
                violations.append(
                    f"[O.2 outline truncated no-children] {path}: "
                    "'truncated': true must NOT carry 'children'. "
                    "A cut-off node's members were not walked; emitting 'children' "
                    "(even []) would falsely read as 'measured-empty'. "
                    "See spec §4.2 Contract 1."
                )

    # O.2 — truncation_reason: validate if present
    if has_truncation_reason:
        reason_val = tree["truncation_reason"]
        if not isinstance(reason_val, str):
            violations.append(
                f"[O.2 outline truncation_reason type] {path}.truncation_reason: "
                f"expected str; got {type(reason_val).__name__!r} ({_truncate(reason_val)})."
            )
        elif reason_val not in _VALID_OUTLINE_TRUNCATION_REASONS:
            violations.append(
                f"[O.2 outline truncation_reason value] {path}.truncation_reason: "
                f"value {reason_val!r} is not recognised. "
                f"Must be one of {sorted(_VALID_OUTLINE_TRUNCATION_REASONS)}."
            )

    # O.3 — truncation_reason without truncated is forbidden
    if has_truncation_reason and not has_truncated:
        violations.append(
            f"[O.3 outline truncation_reason without truncated] {path}: "
            "'truncation_reason' is present but 'truncated' is absent. "
            "'truncation_reason' must only appear alongside 'truncated': true. "
            "See spec §4.2 Contract 2."
        )

    # O.4 — children: if present, must be a list of OutlineTree
    if has_children:
        children_val = tree["children"]
        if not isinstance(children_val, list):
            violations.append(
                f"[O.4 outline children type] {path}.children: "
                f"expected a list (possibly empty) of OutlineTree; "
                f"got {type(children_val).__name__!r} ({_truncate(children_val)})."
            )
        else:
            for idx, child in enumerate(children_val):
                _check_outline_tree_node(child, f"{path}.children[{idx}]", violations)


def _check_outline_structural_floor(
    response: dict[str, Any],
    violations: list[str],
) -> None:
    """O.1–O.4 — Validate the structural floor of an ``OutlineTree`` response.

    Entry point for the ``outline`` operation.  Delegates to
    ``_check_outline_tree_node`` which recurses through the whole tree.

    Layering (A.*) is run separately by ``_check_layering`` and already
    reaches every nested dict/list via ``_walk``, so all ``node`` Stubs and
    ``children`` items at any depth are covered without duplication.

    Args:
        response: The OutlineTree dict returned by the ``outline`` operation.
        violations: Mutable list to append violation messages to.
    """
    _check_outline_tree_node(response, "", violations)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def lint_response(response: dict[str, Any], operation: str) -> None:
    """Run all conformance checks against a single operation response.

    Accumulates ALL violations before raising so the caller sees every problem
    at once.  The linter is pure (no I/O, no analyzer instantiation).

    Args:
        response: The dict returned by resolve / resolve_at / inspect / expand /
            outline, or a standalone Stub dict.
        operation: One of ``"resolve"``, ``"resolve_at"``, ``"inspect"``,
            ``"expand"``, ``"trace"``, ``"outline"``, ``"stub"`` — used in error
            messages and for operation-specific contract checks:
            - ``inspect``  gets B.3 Phase 4 cross-check
            - ``expand``   gets E.1–E.4 structural-floor + top-level source exemption
            - ``trace``    gets T.1–T.4 Subgraph structural-floor
            - ``outline``  gets O.1–O.4 OutlineTree structural-floor (recursive)
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
    elif operation == "trace":
        _check_trace_structural_floor(response, violations)
    elif operation == "stub":
        _check_stub_structural_floor(response, "", violations)
    elif operation == "outline":
        _check_outline_structural_floor(response, violations)
    else:
        _check_absence_vs_zero(response, operation, violations)

    if violations:
        header = (
            f"ConformanceViolation: {len(violations)} rule(s) violated "
            f"in {operation!r} response:\n"
        )
        body = "\n\n".join(f"  [{i + 1}] {v}" for i, v in enumerate(violations))
        raise ConformanceViolation(header + body)
