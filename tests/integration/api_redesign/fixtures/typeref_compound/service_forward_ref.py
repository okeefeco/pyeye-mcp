"""Cross-fixture invariant (e) from acceptance criterion #14 — forward ref.

Exercises the NO-GUESS rule: a quoted forward-reference annotation whose
target does NOT exist anywhere in the project must yield a TypeRef with
``raw`` carrying the forward-ref content and ``handle`` ABSENT (per the
absence-vs-zero invariant). A wrong handle is worse than an absent one;
the spec explicitly bans best-effort heuristic resolution at this leaf.

``DoesNotExist`` is intentionally not defined anywhere in the
``typeref_compound`` fixture project — neither imported nor declared.
The conformance test asserts ``"handle" not in node`` to pin the rule.

``# noqa: F821`` keeps ruff's undefined-name check from complaining about
the deliberately-unresolvable forward ref. Removing the suppression would
cause ruff to either flag the line or trigger a fix that defeats the
test contract.
"""


def future(x: "DoesNotExist") -> None:  # noqa: F821
    """Forward-ref to a non-existent symbol — pins the no-guess rule."""
    _ = x  # silence unused-arg without changing the annotation surface
