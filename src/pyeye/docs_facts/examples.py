"""Executed documentation examples (#828, design §4, D10 and C10).

A fenced block whose info string is ``json pyeye-example tool=<tool>`` is a
runnable example: its body is the call's arguments as a JSON object.
``project_path`` is supplied by the runner and never written in the doc. An
optional ``json pyeye-output`` block directly after it shows the output::

    ```json pyeye-example tool=inspect
    {"handle": "myapp.config.Settings"}
    ```

    ```json pyeye-output
    {"found": true, "kind": "class", "…": "<omitted>"}
    ```

``tests/test_docs_examples.py`` runs every example against a fixture project
(``fixture=<name>`` picks a directory under ``tests/fixtures/``; the default is
``docs_examples``), lints the response with ``tests/conformance/response_linter.py``
and matches any shown output with :func:`match_shown`.

This module only parses and matches; ``check`` reports its problems, so a
malformed tag fails CI even without the test run. It is strict: an info string
naming ``pyeye-`` that doesn't fit the grammar is a problem, never prose.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any

from .binding import Problem, fences
from .docs import DocEntry

EXAMPLE_TAG = "pyeye-example"
OUTPUT_TAG = "pyeye-output"
DEFAULT_FIXTURE = "docs_examples"
_EXAMPLE_KEYS = {"tool", "fixture"}

#: C10: an object level that leaves out real keys says so with this entry.
OMITTED_KEY = "…"
#: C10: the value of :data:`OMITTED_KEY`, and the last item of a trimmed array.
OMITTED = "<omitted>"
#: C10: ``"k": "<absent>"`` asserts that ``k`` is NOT in the real object.
ABSENT = "<absent>"
#: Values compared exactly: a structure-only match must not let ``found: true``
#: stand for ``found: false``.
DISCRIMINATORS = frozenset({"found", "kind", "reason", "ambiguous"})


@dataclass(frozen=True)
class Example:
    """One runnable example.

    Attributes:
        line: 1-based line of the example's opener.
        tool: The MCP tool it calls.
        fixture: The fixture project directory under ``tests/fixtures/``.
        args: The call's arguments (without ``project_path``).
        output: The shown output, or ``None`` when the example shows none.
    """

    line: int
    tool: str
    fixture: str
    args: dict[str, Any]
    output: Any = None

    @property
    def shows_output(self) -> bool:
        """True if a ``pyeye-output`` block follows the example."""
        return self.output is not None


def allows_examples(entry: DocEntry) -> bool:
    """Where runnable examples may live: ``docs/api/``, ``docs/reference/`` and skills."""
    return entry.path.startswith(("docs/api/", "docs/reference/")) or entry.kind == "skill"


def _parse_tag(info: str) -> tuple[str, dict[str, str]] | str | None:
    """``(tag, keys)`` for a pyeye fence, a problem message, or ``None`` for prose."""
    if "pyeye-" not in info:
        return None
    tokens = info.split()
    if len(tokens) < 2 or tokens[0] != "json" or tokens[1] not in (EXAMPLE_TAG, OUTPUT_TAG):
        return (
            f"malformed example tag {info!r}: write `json {EXAMPLE_TAG} tool=<tool>` "
            f"or `json {OUTPUT_TAG}`"
        )
    keys: dict[str, str] = {}
    for token in tokens[2:]:
        name, sep, value = token.partition("=")
        if not sep or not value or name in keys or name not in _EXAMPLE_KEYS:
            return f"bad example key {token!r} in {info!r}: use tool=<tool> [fixture=<name>]"
        keys[name] = value
    if tokens[1] == OUTPUT_TAG and keys:
        return f"`{OUTPUT_TAG}` takes no keys: {info!r}"
    if tokens[1] == EXAMPLE_TAG and "tool" not in keys:
        return f"`{EXAMPLE_TAG}` needs tool=<tool>: {info!r}"
    return tokens[1], keys


def parse_examples(text: str) -> tuple[list[Example], list[Problem]]:
    """The runnable examples in *text*, and every problem with their tags or bodies."""
    examples: list[Example] = []
    problems: list[Problem] = []
    lines = text.splitlines()
    previous: tuple[Example, int] | None = None  # the last example and its closer line
    for fence in fences(text):
        tag = _parse_tag(fence.info)
        if tag is None:
            previous = None
            continue
        if isinstance(tag, str):
            problems.append(Problem(fence.line, tag))
            previous = None
            continue
        kind, keys = tag
        try:
            body = json.loads(text[fence.body_start : fence.body_end])
        except ValueError as error:
            problems.append(Problem(fence.line, f"the {kind} body is not JSON: {error}"))
            previous = None
            continue
        if kind == EXAMPLE_TAG:
            if not isinstance(body, dict):
                problems.append(Problem(fence.line, "an example's body must be a JSON object"))
            elif "project_path" in body:
                problems.append(
                    Problem(fence.line, "don't write project_path; the runner supplies it")
                )
            else:
                example = Example(
                    fence.line, keys["tool"], keys.get("fixture", DEFAULT_FIXTURE), body
                )
                examples.append(example)
                previous = (example, fence.end_line or len(lines))
                continue
            previous = None
            continue
        # An output block: it must directly follow an example (blank lines only).
        between = lines[previous[1] : fence.line - 1] if previous else None
        if previous is None or between is None or any(ln.strip() for ln in between):
            problems.append(Problem(fence.line, f"a `{OUTPUT_TAG}` block must follow an example"))
        elif previous[0].shows_output:
            problems.append(Problem(fence.line, "an example can show only one output"))
        else:
            shown = replace(previous[0], output=body)
            examples[-1] = shown
            previous = (shown, fence.end_line or len(lines))
            continue
        previous = None
    return examples, problems


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _match_key(key: str, value: Any, real: dict[str, Any], where: str, out: list[str]) -> None:
    if value == ABSENT:
        if key in real:
            out.append(f"{where}: shown as {ABSENT}, but the response has it")
        return
    if key not in real:
        out.append(f"{where}: shown, but not in the response")
        return
    _match(value, real[key], where, out)
    if key in DISCRIMINATORS and value != real[key]:
        out.append(f"{where}: shown as {value!r}, but the response has {real[key]!r}")


def _match_object(shown: dict[str, Any], real: Any, path: str, out: list[str]) -> None:
    if not isinstance(real, dict):
        out.append(f"{path}: shown as an object, but the response has {_kind(real)}")
        return
    trimmed = OMITTED_KEY in shown
    if trimmed and shown[OMITTED_KEY] != OMITTED:
        out.append(f'{path}: "{OMITTED_KEY}" must be "{OMITTED}"')
    shown_keys = {key for key in shown if key != OMITTED_KEY}
    for key in sorted(shown_keys):
        _match_key(key, shown[key], real, f"{path}.{key}", out)
    left_out = sorted(set(real) - shown_keys)
    if left_out and not trimmed:
        out.append(f'{path}: leaves out {left_out} without "{OMITTED_KEY}": "{OMITTED}" (C10)')
    if trimmed and not left_out:
        out.append(f'{path}: says "{OMITTED_KEY}": "{OMITTED}", but nothing is left out')


def _match_array(shown: list[Any], real: Any, path: str, out: list[str]) -> None:
    if not isinstance(real, list):
        out.append(f"{path}: shown as an array, but the response has {_kind(real)}")
        return
    trimmed = bool(shown) and shown[-1] == OMITTED
    items = shown[:-1] if trimmed else shown
    if len(items) > len(real):
        out.append(f"{path}: shows {len(items)} items, but the response has {len(real)}")
        return
    if len(items) < len(real) and not trimmed:
        out.append(
            f'{path}: shows {len(items)} of {len(real)} items without a final "{OMITTED}" (C10)'
        )
    if trimmed and len(items) == len(real):
        out.append(f'{path}: ends with "{OMITTED}", but every item is shown')
    for i, (item, actual) in enumerate(zip(items, real, strict=False)):
        _match(item, actual, f"{path}[{i}]", out)


def _match(shown: Any, real: Any, path: str, out: list[str]) -> None:
    if isinstance(shown, dict):
        _match_object(shown, real, path, out)
    elif isinstance(shown, list):
        _match_array(shown, real, path, out)
    elif _kind(shown) != _kind(real):
        out.append(f"{path}: shown as {_kind(shown)}, but the response has {_kind(real)}")


def match_shown(shown: Any, real: Any) -> list[str]:
    """Where *shown* output fails to match the structure of the *real* response (C10).

    - Every shown key exists in the response with the same JSON kind, recursively.
    - A level that leaves out keys carries ``"…": "<omitted>"``; a level that
      carries it must leave something out.
    - ``"k": "<absent>"`` holds only if ``k`` is not in the response.
    - Array items match the response's first items in order; fewer items end
      with ``"<omitted>"``; more items, or a needless ``"<omitted>"``, fail.
    - Values are ignored, except :data:`DISCRIMINATORS`, which must be equal.

    Returns:
        One message per mismatch, with a ``$.a.b[0]`` path; empty when it matches.
    """
    out: list[str] = []
    _match(shown, real, "$", out)
    return out
