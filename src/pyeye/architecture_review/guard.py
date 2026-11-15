"""Cross-derivation guard for the architecture-review auditor (the #494 guard).

This module implements **stage 2** of the confidence-promotion chain, run
*after* the reproduction gate (:mod:`pyeye.architecture_review.gate`).

Why it exists
-------------
The reproduction gate checks **reproducibility, not truth**: a reproducibly
*wrong* Tier-1 fact — e.g. pyeye's ``imports`` edge silently dropping a real
import (#494) — sails through the gate as ``deterministic_single`` because the
error reproduces on every re-run. The cross-derivation guard catches that by
corroborating each surviving ``deterministic_single`` finding's underlying
Tier-1 fact against an **independent second derivation**.

Independence is the whole point
-------------------------------
Without independence the guard is theatre. The corroborating derivation MUST be
independent of the pyeye edge that produced the fact: re-derive from **source
text / AST** (a fresh read of the relevant span) or from an **LSP**, then
compare. It must **never** corroborate a pyeye fact with another pyeye
primitive that could inherit the same defect, and **never** reuse the auditor's
own ``evidence`` field. #494 was caught *precisely because* a source-AST read of
the import statements disagreed with the suspect ``imports`` edge.

This module therefore deliberately imports **no** pyeye edge / import-analysis
machinery. :func:`imports_via_ast` is a from-scratch stdlib :mod:`ast` reader —
the concrete #494 corroborator. :func:`apply_cross_derivation_guard` is a pure
helper that applies the verdict via an injected ``corroborate_fn`` (the
orchestrator wires the independent derivation in), which keeps the unit tests
deterministic while the acceptance test proves independence with a real
AST corroborator.

Verdict
-------
The corroborator answers one of three states (#499):

- ``"corroborated"`` (or ``True``): the finding keeps ``deterministic_single``.
- ``"divergent"`` (or ``False``): the guard rewrites ``grade`` to ``"ambiguous"``
  and sets ``possible_extractor_bug = True``. It **surfaces** a possible extractor
  bug, it does **not** confirm one.
- ``"cannot_confirm"``: the independent derivation could not decide, e.g. an
  import is listed in the edge's ``unresolved_imports`` or the source does not
  parse. The finding is left unpromoted (``grade: "ambiguous"``) for human review,
  and is **not** flagged as an extractor bug. A binary corroborator would collapse
  this into silent agreement or a false divergence, the #494 failure class.

Every non-corroborated finding carries ``corroboration`` naming its state.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, Literal

_CANDIDATE_GRADE: str = "deterministic_single"
_DOWNGRADE_GRADE: str = "ambiguous"

CORROBORATED: Final = "corroborated"
DIVERGENT: Final = "divergent"
CANNOT_CONFIRM: Final = "cannot_confirm"

# A corroborator's verdict (#499). ``True``/``False`` remain accepted aliases
# for ``"corroborated"``/``"divergent"``.
Corroboration = Literal["corroborated", "divergent", "cannot_confirm"]

_BOOL_VERDICTS: dict[bool, Corroboration] = {True: CORROBORATED, False: DIVERGENT}
_VERDICTS: frozenset[str] = frozenset({CORROBORATED, DIVERGENT, CANNOT_CONFIRM})


def imports_via_ast(module_file: Path) -> set[str]:
    """Independently extract imported module names from a Python file via ``ast``.

    This is the SECOND, independent derivation for layering / import facts: it
    reads source text and parses it with the stdlib :mod:`ast` module — it does
    NOT use pyeye's ``imports`` edge, so it cannot inherit that edge's defects
    (#494). The orchestrator wires this into the guard's corroborator for
    import / layering findings.

    Args:
        module_file: Path to the Python source file to read and parse. Read as
            UTF-8 text; the path is never stringified into a key.

    Returns:
        The set of imported module-name strings. ``import a.b`` and
        ``import a.b as c`` both contribute ``"a.b"``; ``from a.b import x``
        contributes ``"a.b"``; relative imports (``from . import s`` /
        ``from .pkg import x``) contribute the dotted module name without the
        leading dots (``""`` becomes the bare names — see below). A bare
        ``from . import sibling`` contributes ``"sibling"`` (the imported name),
        since there is no module portion.

    Note:
        This reader uses :func:`ast.walk`, so it is **scope-inclusive**: it
        collects imports nested inside functions, classes and
        ``if TYPE_CHECKING:`` blocks, not only module-level ones. This is a
        deliberate, documented choice for increment A, not a bug. Implication
        for the orchestrator: if pyeye's ``imports`` edge is top-level-only, the
        corroborator comparing against this set must reconcile scope. Any
        residual mismatch errs toward over-flagging ``possible_extractor_bug``
        — the spec's intended SAFE direction (more human review, never silently
        passing a wrong fact).
    """
    tree = ast.parse(module_file.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                # ``from pkg.sub import x`` / ``from .pkg import x`` -> "pkg.sub"
                names.add(node.module)
            else:
                # ``from . import sibling`` has no module portion; record the
                # imported names themselves (the only module-level identifiers).
                for alias in node.names:
                    names.add(alias.name)
    return names


def _covers(unresolved_target: str, ast_import: str) -> bool:
    """Whether an ``unresolved_imports`` target accounts for an AST import.

    The edge reports the intended dotted target (``from pkg.sub import thing`` ->
    ``"pkg.sub.thing"``, a relative import made absolute), while
    :func:`imports_via_ast` reports the module portion without leading dots
    (``"pkg.sub"``, or ``"sibling"`` for ``from . import sibling``). A target
    covers an import when the import is a whole dotted run inside it. Leniency
    here only ever turns a divergence into ``cannot_confirm`` (human review),
    never into agreement.
    """
    return f".{ast_import}." in f".{unresolved_target}."


def corroborate_imports(
    claimed_imports: set[str],
    unresolved_imports: list[str],
    module_file: Path,
) -> Corroboration:
    """Corroborate an import-set fact against an independent AST read (#499).

    Compares the edge-derived *claimed_imports* (the resolved module names) and
    its *unresolved_imports* (targets the edge saw but could not resolve) with
    :func:`imports_via_ast` of *module_file*.

    Returns:
        - ``"cannot_confirm"`` when the AST side cannot derive the set (the file
          is unreadable or does not parse), or when the edge reports any
          unresolved import and nothing else diverges: an unresolved import is
          neither agreement nor evidence of an extractor bug.
        - ``"divergent"`` when the claim lists an import the source does not
          have, or omits one that no ``unresolved_imports`` entry accounts for
          (the #494 silent drop). A real divergence wins over an unresolved one.
        - ``"corroborated"`` when the sets agree and nothing is unresolved.
    """
    try:
        ast_imports = imports_via_ast(module_file)
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return CANNOT_CONFIRM

    if claimed_imports - ast_imports:
        return DIVERGENT
    missing = ast_imports - claimed_imports
    if any(not any(_covers(u, m) for u in unresolved_imports) for m in missing):
        return DIVERGENT
    if unresolved_imports:
        return CANNOT_CONFIRM
    return CORROBORATED


def _normalise_verdict(verdict: object) -> Corroboration:
    if isinstance(verdict, bool):
        return _BOOL_VERDICTS[verdict]
    if isinstance(verdict, str) and verdict in _VERDICTS:
        return verdict  # type: ignore[return-value]
    raise ValueError(
        f"corroborate_fn returned {verdict!r}; expected a bool or one of "
        f"{sorted(_VERDICTS)} (corroboration verdict, #499)"
    )


def apply_cross_derivation_guard(
    findings: list[dict[str, Any]],
    corroborate_fn: Callable[[dict[str, Any]], bool | Corroboration],
) -> list[dict[str, Any]]:
    """Second promotion stage: corroborate each post-gate ``deterministic_single``.

    For each finding with ``grade == "deterministic_single"``, call
    ``corroborate_fn(finding)`` — the INDEPENDENT re-derivation supplied by the
    orchestrator (source / AST or LSP, never the same pyeye edge and never the
    finding's own ``evidence``). On ``"divergent"`` / ``False`` (the independent
    derivation diverges from the finding's claimed Tier-1 fact), rewrite the
    grade to ``"ambiguous"`` and set ``possible_extractor_bug = True`` (surface,
    do not confirm). On ``"cannot_confirm"`` (#499), rewrite the grade to
    ``"ambiguous"`` WITHOUT the extractor-bug flag: unpromoted, needs human
    review. All other findings pass through unchanged and ``corroborate_fn`` is
    NOT called for them. Order is preserved.

    The helper is **pure**: it performs no real derivation itself — all
    independent derivation is delegated to ``corroborate_fn``. Input dicts are
    never mutated; a new dict copy is returned for any downgraded finding.

    Args:
        findings: The post-gate findings (output of the reproduction gate).
        corroborate_fn: ``(finding) -> verdict`` called once per
            ``deterministic_single`` candidate. The verdict is ``"corroborated"``
            / ``True`` (agrees), ``"divergent"`` / ``False`` (diverges) or
            ``"cannot_confirm"`` (could not decide). For import facts,
            :func:`corroborate_imports` produces it. MUST be independent of the
            pyeye edge that produced the fact and of the auditor's stored
            ``evidence``.

    Returns:
        A new list, same order and length as *findings*. Non-candidates **and
        corroborated candidates** are the same objects as in *findings* (not
        copied). Divergent and cannot-confirm candidates are new dicts with
        ``grade: "ambiguous"`` and ``corroboration`` set to the verdict; only a
        divergent one also gets ``possible_extractor_bug: True``.

    Raises:
        ValueError: *corroborate_fn* returned something that is not a verdict, so
            it can never be misread as agreement or divergence.
    """
    result: list[dict[str, Any]] = []
    for finding in findings:
        if finding.get("grade") != _CANDIDATE_GRADE:
            # Non-candidate: pass through unchanged, never call corroborate_fn.
            result.append(finding)
            continue

        verdict = _normalise_verdict(corroborate_fn(finding))
        if verdict == CORROBORATED:
            # Independent derivation agrees: keep the confident grade.
            result.append(finding)
        elif verdict == DIVERGENT:
            # Divergence: surface a possible extractor bug, do not confirm it.
            result.append(
                {
                    **finding,
                    "grade": _DOWNGRADE_GRADE,
                    "corroboration": DIVERGENT,
                    "possible_extractor_bug": True,
                }
            )
        else:
            # Cannot confirm (#499): unpromoted for human review, not a bug flag.
            result.append({**finding, "grade": _DOWNGRADE_GRADE, "corroboration": CANNOT_CONFIRM})

    return result
