"""The ``structure`` kind: architecture facts about any codebase (RFC #1083 step 2, #1092).

A generic built-in kind (:mod:`..kinds`), configured per repository as data::

    [[tool.pyeye.docs_facts.extractors]]
    kind = "structure"
    include = ["src/*"]
    exclude = ["*/tests/*"]

It runs :mod:`..structure` (the dump, coverage, candidates and relations) over
the repository and yields, under its ``prefix`` (default ``arch``):

* ``<p>.members.<handle>``: each module's and class's functions, classes and
  methods, with signatures, one-line docstrings and what pyeye couldn't read;
* ``<p>.imports.<module>``: what a module imports at runtime, only under
  ``TYPE_CHECKING``, and unresolved; ``measured`` says whether pyeye answered;
* ``<p>.imported_by.<module>``: the SET of areas whose modules import it when
  ``areas`` are configured (#1175, amending Q6), else of top-level packages;
  never a count; ``None`` when pyeye couldn't measure it;
* ``<p>.coverage.gaps``: what the dump doesn't account for, by category
  (ruling Q4); the ``structure-coverage`` rule fails ``check`` on each one;
  ``<p>.coverage.unreadable`` and ``<p>.coverage.refused`` are reported, not gaps;
* ``<p>.cross.<area>``: the candidate pairs touching an area that pyeye's facts
  label (``delegates``, ``override``, ``sibling``), and the sides with an
  unconditional deprecation (a flag, never a label). Ruling Q2: only these are
  facts. The candidates themselves and their scores are a judgement, so they go
  on an advisory page (``candidates_page``) that ``check`` never compares;
* ``<p>.pairs.<area>``: each curated pair touching an area, labelled or
  "possible duplicate (unverified)" (#1175). Curated pairs are committed planner
  data, not a score, so all of them are facts; a rejected pair is neither
  labelled nor listed as a candidate again.

It brings three rules, built for its prefix so a custom one keeps them:
``layering`` (``CHECK no-import: A -> B`` lines on the pages, against the
imports facts), ``structure-coverage``, and ``architecture-handles`` (every
handle an ``architecture_pages`` page names resolves against the members
facts, #1176; :mod:`..structure.handles` states the handle convention). Static only (ruling C19): nothing
imports or runs the analysed code.
"""

from __future__ import annotations

import contextlib
import fnmatch
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...decision_sites import pyeye_resolver
from .. import rules
from ..facts import (
    FACT_ID,
    Advisory,
    Bindable,
    ExtractionError,
    Fact,
    KindOptionsError,
    code,
    code_list,
    table,
    text,
)
from ..registry import Extractor
from ..structure import (
    candidates,
    coverage,
    dump,
    handles as page_handles,
    layering,
    options,
    relations,
)

#: The coverage categories that are gaps (ruling Q4), in report order.
GAP_CATEGORIES = (
    "missing",
    "phantom",
    "unparseable",
    "unmapped",
    "unresolved",
    "skipped",
    "unidentifiable",
    "unknown_pairs",
    "unassigned",
)

#: Page kinds the layering rule reads ``CHECK`` lines on.
_CHECK_KINDS: frozenset[Any] = frozenset({"prose", "skill"})


def structure(table_: Mapping[str, Any]) -> Extractor:
    """The ``structure`` kind's extractor, from its config options.

    Raises:
        KindOptionsError: If an option isn't valid (:func:`..structure.options.parse`).
    """
    try:
        opts = options.parse(table_)
    except ValueError as error:
        raise KindOptionsError(str(error)) from error
    return Extractor(
        "structure",
        (opts.prefix,),
        lambda root: extract(root, opts),
        rules=(
            layering_rule(opts.prefix),
            coverage_rule(opts.prefix),
            handles_rule(opts.prefix, opts.architecture_pages),
        ),
    )


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Collected:
    """Everything one run measured, for :func:`build`.

    Attributes:
        dump: The collected structure.
        coverage: The dump against the files on disk.
        areas: Module -> area.
        candidates: The scored candidates at or above ``min_score``.
        curated: The configured ``pairs`` whose handles are both in the dump.
        relations: The label of every candidate and curated pair, once each.
        unknown_pairs: The configured pairs naming a handle the dump lacks.
        refused: Compiled modules ``strict_source`` refused.
        unassigned: With areas configured, the modules no area matches (#1175).
        by_area: Whether areas are configured, so facts are read by area.
    """

    dump: dump.Dump
    coverage: coverage.Coverage
    areas: Mapping[str, str]
    candidates: tuple[candidates.Candidate, ...]
    relations: tuple[relations.Relation, ...]
    curated: tuple[tuple[str, str], ...] = ()
    unknown_pairs: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()
    unassigned: tuple[str, ...] = ()
    by_area: bool = False


def extract(root: Path, opts: options.Options) -> list[Bindable | Advisory]:
    """Collect *root*'s structure through pyeye and build its facts."""
    try:
        opts = options.load(opts, root)  # the areas and pairs data files (#1175)
    except ValueError as error:
        raise ExtractionError(str(error)) from error
    guard: contextlib.AbstractContextManager[list[str]] = (
        dump.source_only() if opts.strict_source else contextlib.nullcontext([])
    )
    rejected = {frozenset((a, b)) for a, b, _ in opts.rejected}
    with guard as refused, dump.Pyeye(root) as ops:
        found = dump.collect(root, include=opts.include, exclude=opts.exclude, pyeye=ops)
        cov = coverage.compare(found, root, opts.include, opts.exclude)
        area_map = area_of([m.handle for m in found.modules], opts.areas)
        scored = tuple(
            c
            for c in candidates.score(found, area_map, within_areas=opts.within_areas)
            if c.score >= opts.min_score and frozenset((c.a, c.b)) not in rejected
        )
        curated, unknown = known_pairs(opts.pairs, found)
        _, unknown_rejected = known_pairs([(a, b) for a, b, _ in opts.rejected], found)
        labelled = tuple(
            relations.relate_all(to_label(scored, curated), relations.PyeyeFacts(ops, found), found)
        )
    return build(
        opts,
        Collected(
            found,
            cov,
            area_map,
            scored,
            labelled,
            curated,
            unknown + tuple(f"{u} (rejected)" for u in unknown_rejected),
            tuple(sorted(set(refused))),
            unassigned(area_map, opts.areas),
            bool(opts.areas),
        ),
    )


def unassigned(
    area_map: Mapping[str, str], areas: Sequence[tuple[str, Sequence[str]]]
) -> tuple[str, ...]:
    """The modules no configured area matches: a gap, so the planner re-runs (#1175).

    With no areas configured every module is its own area, by design, and
    nothing is unassigned. :func:`area_of` refuses a module named like an area,
    so a module that is its own area here matched none.
    """
    if not areas:
        return ()
    return tuple(sorted(m for m, area in area_map.items() if area == m))


def known_pairs(
    pairs: Sequence[tuple[str, str]], found: dump.Dump
) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    """The curated pairs whose handles the dump holds, and the others as gaps."""
    known: list[tuple[str, str]] = []
    unknown: list[str] = []
    for a, b in pairs:
        missing = [h for h in (a, b) if h not in found.by_handle]
        if missing:
            unknown.append(f"{a} ~ {b} (not in the dump: {', '.join(missing)})")
        else:
            known.append((a, b))
    return tuple(known), tuple(unknown)


def to_label(
    scored: Iterable[candidates.Candidate], curated: Iterable[tuple[str, str]]
) -> list[tuple[str, str]]:
    """Every pair to label, once each (a curated pair may also be a candidate)."""
    out: list[tuple[str, str]] = []
    seen: set[frozenset[str]] = set()
    for pair in [*((c.a, c.b) for c in scored), *curated]:
        if frozenset(pair) not in seen:
            seen.add(frozenset(pair))
            out.append(pair)
    return out


def area_of(modules: Sequence[str], areas: Sequence[tuple[str, Sequence[str]]]) -> dict[str, str]:
    """Each module's area: the one configured area whose patterns match it, else itself.

    Raises:
        ExtractionError: If a module matches two areas, or a module no area
            matches has the same name as an area (they'd merge silently).
    """
    out: dict[str, str] = {}
    names = {area for area, _ in areas}
    for module in modules:
        hits = [a for a, patterns in areas if any(fnmatch.fnmatchcase(module, p) for p in patterns)]
        if len(hits) > 1:
            raise ExtractionError(
                f"structure: module {module!r} matches areas {hits}; give each module one area"
            )
        if not hits and module in names:
            raise ExtractionError(
                f"structure: module {module!r} is in no area but is named like area "
                f"{module!r}; rename the area or add the module to it"
            )
        out[module] = hits[0] if hits else module
    return out


def fact_id(prefix: str, family: str, name: str) -> str | None:
    """``<prefix>.<family>.<name>``, or ``None`` if *name* can't be a fact ID's tail."""
    candidate = f"{prefix}.{family}.{name}"
    return candidate if FACT_ID.fullmatch(candidate) else None


def build(opts: options.Options, found: Collected) -> list[Bindable | Advisory]:
    """Every fact (and the advisory page, if configured) from one run's measurements."""
    prefix = opts.prefix
    out: list[Bindable | Advisory] = []
    unidentifiable: set[str] = set()

    def add(family: str, name: str, value: Any, markdown: str) -> None:
        fid = fact_id(prefix, family, name)
        if fid is None:
            unidentifiable.add(name)
        else:
            out.append(Fact(fid, value, markdown))

    for owner, value in members_by_owner(found.dump).items():
        add("members", owner, value, members_markdown(value))
    for module in found.dump.modules:
        add("imports", module.handle, imports_value(module), imports_markdown(module))
        importers = (
            importing_areas(module, found.areas) if found.by_area else importing_packages(module)
        )
        add("imported_by", module.handle, importers, imported_by_markdown(importers, found.by_area))
    for area, value in cross_by_area(found).items():
        add("cross", area, value, cross_markdown(value))
    for area, curated in pairs_by_area(found).items():
        add("pairs", area, curated, pairs_markdown(curated))
    gaps = gap_lists(found.coverage, sorted(unidentifiable), found.unknown_pairs, found.unassigned)
    out.append(Fact(f"{prefix}.coverage.gaps", gaps, gaps_markdown(gaps)))
    unreadable = list(found.coverage.unreadable)
    out.append(
        Fact(
            f"{prefix}.coverage.unreadable",
            unreadable,
            _listed("pyeye couldn't read", unreadable, "pyeye read every definition."),
        )
    )
    refused = list(found.refused)
    out.append(
        Fact(
            f"{prefix}.coverage.refused",
            refused,
            _listed("Compiled modules refused", refused, "No compiled module was refused."),
        )
    )
    if opts.candidates_page:
        out.append(Advisory(opts.candidates_page, candidates_page(opts, found)))
    return out


# ---------------------------------------------------------------------------
# Fact values and their Markdown
# ---------------------------------------------------------------------------


def members_by_owner(found: dump.Dump) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Each module's and class's members and unreadable definitions, by owner handle."""
    owners: dict[str, dict[str, list[dict[str, Any]]]] = {
        m.handle: {"members": [], "unreadable": []} for m in found.modules
    }
    for d in found.definitions:
        if d.kind == "class":
            owners.setdefault(d.handle, {"members": [], "unreadable": []})
    for d in found.definitions:
        owners.setdefault(d.owner, {"members": [], "unreadable": []})["members"].append(
            {
                "name": d.handle.rsplit(".", 1)[-1],
                "kind": d.kind,
                "signature": d.signature,
                "summary": d.summary,
            }
        )
    for u in found.unreadable:
        owner, name = u.handle.rsplit(".", 1)
        owners.setdefault(owner, {"members": [], "unreadable": []})["unreadable"].append(
            {"name": name, "kind": u.kind, "reason": u.reason}
        )
    return owners


def members_markdown(value: Mapping[str, list[dict[str, Any]]]) -> str:
    """A members table, then the definitions pyeye couldn't read."""
    rows = [
        (
            code(m["name"]),
            m["kind"],
            code(m["signature"]) if m["signature"] else "(no signature)",
            text(m["summary"]) if m["summary"] else "",
        )
        for m in value["members"]
    ]
    parts = [table(("Name", "Kind", "Signature", "Summary"), rows)] if rows else ["No members."]
    if value["unreadable"]:
        listed = ", ".join(f"{code(u['name'])} ({text(u['reason'])})" for u in value["unreadable"])
        parts.append(f"pyeye couldn't read: {listed}.")
    return "\n\n".join(parts)


def imports_value(module: dump.Module) -> dict[str, Any]:
    """A module's imports fact: runtime, ``TYPE_CHECKING``-only and unresolved."""
    if not module.measured_imports:
        return {"measured": False}
    return {
        "measured": True,
        "runtime": list(module.imports),
        "type_only": list(module.type_only_imports),
        "unresolved": list(module.unresolved_imports),
    }


def imports_markdown(module: dump.Module) -> str:
    """How a module's imports read."""
    if not module.measured_imports:
        return "pyeye couldn't read its imports."
    lines = [
        _listed("Imports", list(module.imports), "Imports nothing at runtime."),
    ]
    if module.type_only_imports:
        lines.append(f"Only under `TYPE_CHECKING`: {code_list(module.type_only_imports)}.")
    if module.unresolved_imports:
        lines.append(f"Unresolved: {code_list(module.unresolved_imports)}.")
    return "\n".join(lines)


def importing_packages(module: dump.Module) -> list[str] | None:
    """The top-level packages of the modules that import it (ruling Q6), or ``None``."""
    if module.imported_by is None:
        return None
    return sorted({h.split(".", 1)[0] for h in module.importers})


def importing_areas(module: dump.Module, areas: Mapping[str, str]) -> list[str] | None:
    """The areas of the modules that import it (#1175, amending Q6), or ``None``.

    An importer outside the collected scope (a file ``include``/``exclude``
    left out, such as a test) is in no area, so it isn't counted.
    """
    if module.imported_by is None:
        return None
    return sorted({areas[h] for h in module.importers if h in areas})


def imported_by_markdown(importers: list[str] | None, by_area: bool = False) -> str:
    """How the importing areas (or packages) read."""
    if importers is None:
        return "pyeye couldn't measure what imports it."
    head = "Imported from areas" if by_area else "Imported from"
    return _listed(head, importers, "No module in scope imports it.")


def _area(found: Collected, handle: str) -> str:
    module = found.dump.by_handle[handle].module
    return found.areas.get(module, module)


def cross_by_area(found: Collected) -> dict[str, dict[str, Any]]:
    """Each area's pyeye-backed pair facts (ruling Q2): labels and deprecation flags."""

    def area(handle: str) -> str:
        return _area(found, handle)

    out: dict[str, dict[str, Any]] = {
        a: {"labelled": [], "deprecated": []} for a in sorted(set(found.areas.values()))
    }
    deprecated: dict[str, set[str]] = {a: set() for a in out}
    for r in found.relations:
        for side in sorted({area(r.a), area(r.b)}):
            if r.label != relations.UNVERIFIED:
                a, b = sorted((r.a, r.b))  # a fact's value never depends on scan order
                out[side]["labelled"].append({"a": a, "b": b, "label": r.label})
            deprecated[side].update(h for h in r.deprecated if area(h) == side)
    for side, handles in deprecated.items():
        out[side]["labelled"].sort(key=lambda p: (p["a"], p["b"]))
        out[side]["deprecated"] = sorted(handles)
    return out


def pairs_by_area(found: Collected) -> dict[str, list[dict[str, Any]]]:
    """Each area's curated pairs, each labelled or unverified (#1175, within Q2(c)).

    Curated pairs are committed planner data, not a score, so every one is a
    fact, the unlabelled ones as "possible duplicate (unverified)". An area doc's
    "Similar elsewhere" footer binds this.
    """
    by_pair = {frozenset((r.a, r.b)): r for r in found.relations}
    out: dict[str, list[dict[str, Any]]] = {a: [] for a in sorted(set(found.areas.values()))}
    for a, b in found.curated:
        r = by_pair[frozenset((a, b))]
        first, second = sorted((a, b))
        entry = {
            "a": first,
            "b": second,
            "label": r.label,
            "deprecated": sorted(r.deprecated),
            "measured": r.measured,
        }
        for side in sorted({_area(found, a), _area(found, b)}):
            out[side].append(entry)
    for entries in out.values():
        entries.sort(key=lambda e: (e["a"], e["b"]))
    return out


def pairs_markdown(value: Sequence[Mapping[str, Any]]) -> str:
    """How an area's curated pairs read: the "Similar elsewhere" footer."""
    lines = []
    for p in value:
        notes = [f"{code(h)} is deprecated" for h in p["deprecated"]]
        if not p["measured"]:
            notes.append("calls unmeasured")
        extra = f" ({'; '.join(notes)})" if notes else ""
        lines.append(f"- {code(p['a'])} and {code(p['b'])}: {p['label']}{extra}")
    return "\n".join(lines) if lines else "No curated pair touches this area."


def cross_markdown(value: Mapping[str, Any]) -> str:
    """How an area's labelled pairs and deprecated sides read."""
    lines = [f"- {code(p['a'])} and {code(p['b'])}: {p['label']}" for p in value["labelled"]]
    if value["deprecated"]:
        lines.append(f"- Deprecated: {code_list(value['deprecated'])}")
    return "\n".join(lines) if lines else "No candidate pair here has a label from pyeye's facts."


def gap_lists(
    cov: coverage.Coverage,
    unidentifiable: Sequence[str],
    unknown_pairs: Sequence[str] = (),
    unassigned_modules: Sequence[str] = (),
) -> dict[str, list[str]]:
    """The coverage gaps by category (ruling Q4), each list sorted."""
    return {
        "missing": list(cov.missing),
        "phantom": list(cov.phantom),
        "unparseable": list(cov.unparseable),
        "unmapped": list(cov.unmapped),
        "unresolved": list(cov.unresolved),
        "skipped": list(cov.skipped),
        "unidentifiable": list(unidentifiable),
        "unknown_pairs": list(unknown_pairs),
        "unassigned": list(unassigned_modules),
    }


def gaps_markdown(gaps: Mapping[str, Sequence[str]]) -> str:
    """How the coverage gaps read."""
    lines = [
        f"- {category}: {code_list(gaps[category])}"
        for category in GAP_CATEGORIES
        if gaps[category]
    ]
    return "\n".join(lines) if lines else "None: every definition on disk is in the dump."


def _listed(head: str, names: Sequence[str], empty: str) -> str:
    return f"{head}: {code_list(names)}." if names else empty


#: Opens the advisory page: what it is, before anything it shows (designer, #1092).
JUDGMENT_NOTE = (
    "**Judgment, not fact.** These pairs are candidates scored by name, docstring and "
    "parameter overlap. The threshold and filters below decide what counts, and a score "
    "is tunable, so `check` never compares this page and no fact block can bind it. "
    "Only the labels in the cross-area facts (`delegates`, `override`, `sibling`) and "
    "the deprecation flags rest on pyeye's facts. A pair with no label is a possible "
    "duplicate (unverified): read both sides before acting."
)


def filters(opts: options.Options) -> list[str]:
    """The filters that decide which pairs the page lists, as the page states them."""
    return [
        f"score at least {opts.min_score:g}: name overlap + "
        f"{candidates.DOC_WEIGHT:g} x docstring + {candidates.PARAM_WEIGHT:g} x parameters",
        "the two names share at least one word",
        f"a name {candidates.HOOK_OWNERS}+ owners define is an interface hook, not a copy",
        "dunder methods are left out",
        (
            "pairs across areas and inside one area, never inside one owner"
            if opts.within_areas
            else "pairs across areas only"
        ),
    ]


def candidates_page(opts: options.Options, found: Collected) -> str:
    """The advisory page: the scored candidate pairs, labelled a judgment (ruling Q2).

    It is never on the docs site: an advisory page can't be a registered doc
    (``cli.plan`` refuses one that is), and the site publishes registered docs only.
    """
    by_pair = {frozenset((r.a, r.b)): r for r in found.relations}

    def row(score: str, a: str, b: str, a_shown: str, b_shown: str) -> tuple[str, ...]:
        r = by_pair[frozenset((a, b))]
        flags = [f"{code(h)} deprecated" for h in r.deprecated]
        if not r.measured:
            flags.append("callees unmeasured")
        return (score, a_shown, b_shown, r.label, ", ".join(flags))

    rows = [
        row(
            f"{c.score:.2f}",
            c.a,
            c.b,
            f"{code(c.a)} ({text(c.a_area)})",
            f"{code(c.b)} ({text(c.b_area)})",
        )
        for c in found.candidates
    ]
    scored = {frozenset((c.a, c.b)) for c in found.candidates}
    rows.extend(
        row("curated", a, b, code(a), code(b))
        for a, b in found.curated
        if frozenset((a, b)) not in scored
    )
    body = table(("Score", "A", "B", "Label", "Flags"), rows) if rows else "No candidate pairs."
    listed = "\n".join(f"- {f}" for f in filters(opts))
    return (
        f"# Candidate pairs: {opts.prefix} (judgment)\n\n{JUDGMENT_NOTE}\n\n"
        f"Written by `docs_facts generate`. Threshold and filters:\n\n{listed}\n\n{body}\n"
    )


# ---------------------------------------------------------------------------
# Rules, built for a prefix
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModuleImports:
    """A module's imports as its ``<p>.imports.<module>`` fact records them."""

    handle: str
    imports: tuple[str, ...]
    type_only_imports: tuple[str, ...]
    unresolved_imports: tuple[str, ...]
    measured_imports: bool


def modules_from_facts(prefix: str, facts: rules.Facts) -> list[ModuleImports]:
    """Every module's imports, read back from the imports facts."""
    head = f"{prefix}.imports."
    out = []
    for fid, item in sorted(facts.items()):
        if not fid.startswith(head) or not isinstance(item, Fact):
            continue
        value = item.value
        out.append(
            ModuleImports(
                fid[len(head) :],
                tuple(value.get("runtime", ())),
                tuple(value.get("type_only", ())),
                tuple(value.get("unresolved", ())),
                bool(value.get("measured")),
            )
        )
    return out


def layering_findings(prefix: str, page: rules.Page, facts: rules.Facts) -> list[rules.Finding]:
    """A finding per ``CHECK no-import`` line on *page* that isn't verified to hold."""
    found = layering.checks(page.prose)
    if not found:
        return []
    modules = modules_from_facts(prefix, facts)
    findings = []
    for check in found:
        message = layering.message(layering.run(check, modules))
        if message is not None:
            findings.append(rules.Finding(check.line, message))
    return findings


def layering_rule(prefix: str) -> rules.Rule:
    """The ``layering`` rule over the *prefix* facts."""
    return rules.Rule(
        rules.LAYERING,
        _CHECK_KINDS,
        False,
        lambda page, facts: layering_findings(prefix, page, facts),
        requires=frozenset({f"{prefix}.imports."}),
    )


def handles_findings(
    prefix: str, patterns: tuple[str, ...], page: rules.Page, facts: rules.Facts
) -> list[rules.Finding]:
    """A finding per handle *page* names that the *prefix* dump doesn't define (#1176)."""
    if not page_handles.is_architecture_page(page.name, patterns):
        return []
    defined = page_handles.known(prefix, facts)
    resolver = None if page.root is None else pyeye_resolver(page.root)
    return [
        rules.Finding(
            page.line + line - 1,
            f"`{name}` doesn't resolve in the {prefix} dump or with pyeye"
            + (f" ({reason})" if reason else ""),
        )
        for line, name, reason in page_handles.unresolved(page.prose, defined, resolver)
    ]


def handles_rule(prefix: str, patterns: tuple[str, ...]) -> rules.Rule:
    """The ``architecture-handles`` rule over the *prefix* facts, on the *patterns* pages."""
    return rules.Rule(
        rules.ARCHITECTURE_HANDLES,
        _CHECK_KINDS,
        False,
        lambda page, facts: handles_findings(prefix, patterns, page, facts),
        requires=frozenset({f"{prefix}.members."}),
    )


def coverage_problems(prefix: str, facts: rules.Facts) -> list[str]:
    """One problem per coverage gap (ruling Q4)."""
    item = facts.get(f"{prefix}.coverage.gaps")
    gaps: Mapping[str, Iterable[str]] = item.value if isinstance(item, Fact) else {}
    return [
        f"{category} in the {prefix} dump: {name}"
        for category in GAP_CATEGORIES
        for name in gaps.get(category, ())
    ]


def coverage_rule(prefix: str) -> rules.Rule:
    """The ``structure-coverage`` rule over the *prefix* facts: a repository-wide audit."""
    return rules.Rule(
        rules.STRUCTURE_COVERAGE,
        frozenset(),
        False,
        lambda _page, _facts: [],
        requires=frozenset({f"{prefix}.coverage.gaps"}),
        audit=lambda facts: coverage_problems(prefix, facts),
    )
