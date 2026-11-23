"""The architecture review engine: an area against its recorded architecture (#1178, #1132).

The review compares an area's code with the facts and records about it, not
with the whole source. One run, for one area (R3):

1. **Plan** (:func:`plan`): gather the area's ``arch.*`` facts from the
   repository's snapshot (#1092), the ``CHECK`` rules that govern it, and the
   decisions whose ``Applies-to`` sites fall in it.
2. **Mechanical pass**, in the plan, with no judgment:

   - each rule in scope (a ``CHECK no-import: A -> B`` line on a registered page
     whose ``A`` names a module of the area, R2) is run against the area's
     imports facts (:mod:`.structure.layering`). It gives an **adherence** or a
     **deviation** finding, or, when pyeye couldn't read an import, an
     unverified rule, never an adherence;
   - each active decision's ``Applies-to`` sites are resolved through pyeye
     (:mod:`pyeye.decision_sites`, the user's ruling) and matched to the area's
     module globs by canonical handle. A matching decision is a **candidate**
     for the reviewer to confirm, since a decision is prose. A site that
     doesn't resolve is reported, never silently unmatched.

3. **Packet**: the plan's JSON, all a fresh-context reviewer reads.
4. **Validate** (:func:`problems`): the generalised shared validator
   (:func:`.review.architecture_problems`, R6), then the packet's checks.
5. **Report** (:func:`report`), ranked: deviations from rules, deviations from
   decisions and conventions, decisions needed, ambiguities, then adherence as a
   count. No importer-count blast.

No dismissals (R7): a resolved item becomes a decision entry, which the next
run reports adherence to. Static only (C19): nothing of the analysed
repository is imported or run.

Run it as ``python -m pyeye.docs_facts architecture plan|validate|report``.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import decision_sites, decisions
from . import config, docs, review
from .structure import layering, options

#: What a run says when the repository records no architecture for the area (goal 4).
NO_ARCHITECTURE = "no recorded architecture for this area; run /arch-facts first"

#: The decision statuses whose rules still govern their sites.
_GOVERNING = ("active", "amended")

#: The page kinds whose ``CHECK`` lines are rules (as the ``layering`` rule reads them).
_CHECK_KINDS = ("prose", "skill")

#: The report's tiers, in rank order (#1132 §2.5).
TIERS = ("rule_deviations", "record_deviations", "decisions_needed", "ambiguities")


# ---------------------------------------------------------------------------
# Areas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Area:
    """One area (R3): a configured area ID's module patterns, or a module prefix.

    Attributes:
        id: The area ID, or the module prefix.
        patterns: :mod:`fnmatch` patterns on dotted names.
        configured: Whether it comes from the ``structure`` kind's ``areas``.
    """

    id: str
    patterns: tuple[str, ...]
    configured: bool

    def holds(self, handle: str) -> bool:
        """Whether *handle* (a module, or anything inside one) is in the area."""
        parts = handle.split(".")
        names = [".".join(parts[: i + 1]) for i in range(len(parts))]
        return any(fnmatch.fnmatchcase(n, p) for n in names for p in self.patterns)


def area(name: str, opts: options.Options) -> Area:
    """The area *name*: a configured area ID, else the module prefix *name* (R3)."""
    for area_id, patterns in opts.areas:
        if area_id == name:
            return Area(name, tuple(patterns), True)
    return Area(name, (name, f"{name}.*"), False)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def structure_options(root: Path) -> options.Options | None:
    """The ``structure`` kind's options in *root*'s config, or ``None`` if it has none."""
    raw = config.find(root) or {}
    for entry in raw.get("extractors", []) or []:
        if isinstance(entry, Mapping) and entry.get("kind") == "structure":
            return options.parse({k: v for k, v in entry.items() if k != "kind"})
    return None


def snapshot_values(root: Path, setup: Any) -> dict[str, Any]:
    """Every recorded fact's value, from each snapshot file (#1108). No extraction runs."""
    values: dict[str, Any] = {}
    for rel in setup.paths.snapshot_files():
        path = root / rel
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            values.update(data.get("facts", {}))
    return values


@dataclass(frozen=True)
class _Imports:
    """A module's imports, read from its ``<p>.imports.<module>`` fact (:class:`layering.Imports`)."""

    handle: str
    imports: tuple[str, ...]
    type_only_imports: tuple[str, ...]
    unresolved_imports: tuple[str, ...]
    measured_imports: bool


def recorded_modules(prefix: str, values: Mapping[str, Any]) -> list[_Imports]:
    """Every module the snapshot records imports for."""
    head = f"{prefix}.imports."
    out = []
    for fid, value in sorted(values.items()):
        if fid.startswith(head) and isinstance(value, Mapping):
            out.append(
                _Imports(
                    fid[len(head) :],
                    tuple(value.get("runtime", ())),
                    tuple(value.get("type_only", ())),
                    tuple(value.get("unresolved", ())),
                    bool(value.get("measured")),
                )
            )
    return out


def _rules(root: Path, setup: Any) -> list[tuple[str, layering.Check]]:
    """Every ``CHECK`` line on a registered prose or skill page, with its page."""
    found: list[tuple[str, layering.Check]] = []
    for path, entry in docs.registered_files(root, setup.docs):
        if entry.kind in _CHECK_KINDS:
            text = (root / path).read_text(encoding="utf-8")
            found.extend((path, check) for check in layering.checks(text))
    return found


def rule_id(check: layering.Check) -> str:
    """A ``rule`` anchor's ID: the check's text after ``CHECK``."""
    return f"no-import: {check.a} -> {check.b}"


# ---------------------------------------------------------------------------
# Plan and the mechanical pass
# ---------------------------------------------------------------------------


def _finding(area_: Area, category: str, anchor: dict[str, str], **fields: Any) -> dict[str, Any]:
    return {
        "review": review.ARCHITECTURE_REVIEW,
        "area": area_.id,
        "category": category,
        "anchor": anchor,
        **fields,
    }


def _rule_pass(
    area_: Area, modules: Sequence[_Imports], rules: Iterable[tuple[str, layering.Check]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """The rules in scope, the findings they give, and the ones that can't be verified."""
    in_scope, findings, unverified = [], [], []
    for page, check in rules:
        governed = [m for m in modules if layering.under(m.handle, check.a)]
        if not governed:
            continue
        result = layering.run(check, governed)
        anchor = {"kind": "rule", "id": rule_id(check)}
        record = {
            "id": rule_id(check),
            "page": page,
            "line": check.line,
            "violations": [list(v) for v in result.violations],
            "ignored": [list(i) for i in result.ignored],
            "unmeasured": list(result.unmeasured),
        }
        in_scope.append(record)
        if result.violations:
            sites = sorted({m for m, _ in result.violations})
            shown = "; ".join(f"{m} imports {t}" for m, t in result.violations)
            findings.append(
                _finding(
                    area_,
                    "deviation",
                    anchor,
                    problem=f"CHECK {rule_id(check)} ({page}:{check.line}) is broken: {shown}",
                    evidence=sites,
                    recommendation=(
                        f"Remove the runtime import of {check.b} from {', '.join(sites)}, or "
                        f"record a decision that changes the CHECK line at {page}:{check.line}."
                    ),
                )
            )
        elif result.holds:
            findings.append(
                _finding(
                    area_,
                    "adherence",
                    anchor,
                    problem=f"CHECK {rule_id(check)} ({page}:{check.line}) holds",
                    evidence=sorted(m.handle for m in governed),
                )
            )
        else:
            unverified.append({**record, "reason": layering.message(result)})
    return in_scope, findings, unverified


def _decision_pass(
    area_: Area, entries: Iterable[decisions.Entry], resolver: decision_sites.Resolver
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The candidate decisions for the area, and every site that didn't resolve."""
    candidates, unresolved = [], []
    for entry in entries:
        if entry.meta.get("status") not in _GOVERNING:
            continue
        text = decisions.applies_to(entry.body)
        sites = decision_sites.resolve_sites(text, resolver)
        for site in sites:
            if site.handle is None:
                unresolved.append(
                    {"decision": entry.name, "site": site.ref.text, "reason": site.reason}
                )
        matched = [s for s in sites if s.handle is not None and area_.holds(s.handle)]
        if matched:
            candidates.append(
                {
                    "decision": entry.name,
                    "title": entry.meta.get("title", ""),
                    "status": entry.meta.get("status"),
                    "applies_to": text,
                    "sites": [{"text": s.ref.text, "handle": s.handle} for s in matched],
                }
            )
    return candidates, unresolved


def _area_facts(prefix: str, area_: Area, values: Mapping[str, Any]) -> dict[str, Any]:
    """The recorded facts about the area's own definitions, imports and pairs."""
    out: dict[str, Any] = {}
    for family in ("members", "imports", "imported_by"):
        head = f"{prefix}.{family}."
        out.update(
            {f: v for f, v in values.items() if f.startswith(head) and area_.holds(f[len(head) :])}
        )
    cross = f"{prefix}.cross.{area_.id}"
    if cross in values:
        out[cross] = values[cross]
    return dict(sorted(out.items()))


def _area_gaps(prefix: str, area_: Area, values: Mapping[str, Any]) -> dict[str, list[str]]:
    """The coverage gaps inside the area, by category."""
    gaps = values.get(f"{prefix}.coverage.gaps")
    if not isinstance(gaps, Mapping):
        return {}
    return {
        category: sorted(n for n in names if area_.holds(str(n)))
        for category, names in sorted(gaps.items())
        if any(area_.holds(str(n)) for n in names)
    }


def _conventions(root: Path, paths: Iterable[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Each convention document's sections, and a note per missing one."""
    found, notes = [], []
    for path in paths:
        if not (root / path).is_file():
            notes.append(f"convention document {path} doesn't exist")
            continue
        text = (root / path).read_text(encoding="utf-8")
        found.append({"path": path, "sections": [s.slug for s in review.sections(text)]})
    return found, notes


def plan(
    root: Path,
    name: str,
    *,
    decisions_dir: Path | None = None,
    conventions: Sequence[str] = (),
    resolver: decision_sites.Resolver | None = None,
) -> dict[str, Any]:
    """The packet for area *name*: its facts, rules, candidates and mechanical findings.

    Raises:
        config.ConfigError: If *root* has no docs-facts config, or it isn't valid.
    """
    setup = config.load(root)
    opts = structure_options(root)
    packet: dict[str, Any] = {"review": review.ARCHITECTURE_REVIEW, "notes": []}
    if opts is None:
        packet.update(area={"id": name, "patterns": [name, f"{name}.*"], "configured": False})
        packet["notes"].append(f"{NO_ARCHITECTURE} (no structure kind is configured)")
        return _empty(packet)
    area_ = area(name, opts)
    packet.update(
        area={"id": area_.id, "patterns": list(area_.patterns), "configured": area_.configured},
        prefix=opts.prefix,
    )
    values = snapshot_values(root, setup)
    modules = recorded_modules(opts.prefix, values)
    if not modules:
        packet["notes"].append(f"{NO_ARCHITECTURE} (the snapshot records no {opts.prefix}.* facts)")
        return _empty(packet)
    mine = [m for m in modules if area_.holds(m.handle)]
    packet["modules"] = [m.handle for m in mine]
    if not mine:
        packet["notes"].append(f"{NO_ARCHITECTURE} (no recorded module is in area {area_.id!r})")
        return _empty(packet)
    if opts.areas:
        assigned = [Area(i, tuple(p), True) for i, p in opts.areas]
        packet["unassigned"] = [
            m.handle for m in modules if not any(a.holds(m.handle) for a in assigned)
        ]
    rules, findings, unverified = _rule_pass(area_, mine, _rules(root, setup))
    entries, errors = decisions.load(decisions_dir or root / "docs" / "decisions" / "entries")
    packet["notes"].extend(f"decision entry unreadable: {e}" for e in errors)
    candidates, unresolved = _decision_pass(
        area_, entries, resolver or decision_sites.pyeye_resolver(root)
    )
    found_conventions, notes = _conventions(root, conventions)
    packet["notes"].extend(notes)
    packet.update(
        facts=_area_facts(opts.prefix, area_, values),
        gaps=_area_gaps(opts.prefix, area_, values),
        rules=rules,
        unverified_rules=unverified,
        decisions=candidates,
        unresolved_sites=unresolved,
        conventions=found_conventions,
        findings=findings,
    )
    return packet


def _empty(packet: dict[str, Any]) -> dict[str, Any]:
    """A packet with nothing to review: every list present and empty."""
    for key in ("modules", "rules", "unverified_rules", "decisions", "unresolved_sites"):
        packet.setdefault(key, [])
    for key in ("conventions", "findings"):
        packet.setdefault(key, [])
    packet.setdefault("facts", {})
    packet.setdefault("gaps", {})
    return packet


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def problems(
    finding: Mapping[str, Any],
    packet: Mapping[str, Any],
    root: Path | None = None,
    symbols: review.Symbols | None = None,
) -> list[str]:
    """Why a reviewer's *finding* can't be shown; ``[]`` when it can.

    The shared validator's shape (:func:`.review.finding_problems`), then what
    the packet holds: the finding is about the packet's area; a ``rule`` anchor
    comes only from the mechanical pass; a ``decision`` anchor is one of the
    packet's candidates (a decision that doesn't govern the area can't be
    deviated from in it); a ``convention`` anchor is one of its documents; a
    ``fact`` anchor is one of its facts; and every evidence handle is in the area.
    """
    if finding.get("review") != review.ARCHITECTURE_REVIEW:
        return ["an architecture finding says review: 'architecture'"]
    found = review.finding_problems(finding, packet.get("facts", {}), root, symbols)
    area_spec = packet["area"]
    area_ = Area(area_spec["id"], tuple(area_spec["patterns"]), area_spec["configured"])
    if finding.get("area") != area_.id:
        found.append(f"area must be the packet's, {area_.id!r}")
    anchors = [finding.get("anchor"), finding.get("recommendation_anchor")]
    for where, anchor in zip(("anchor", "recommendation_anchor"), anchors, strict=True):
        if isinstance(anchor, Mapping):
            found.extend(_packet_anchor_problems(where, anchor, packet))
    evidence = finding.get("evidence", [])
    if isinstance(evidence, list):
        outside = [e for e in evidence if isinstance(e, str) and not area_.holds(e)]
        if outside:
            found.append(f"evidence outside area {area_.id!r}: {outside}")
    return found


def _packet_anchor_problems(
    where: str, anchor: Mapping[str, Any], packet: Mapping[str, Any]
) -> list[str]:
    kind, anchor_id = anchor.get("kind"), anchor.get("id")
    if kind == "rule":
        return [f"{where}: a rule's adherence or deviation comes from the mechanical pass"]
    if kind == "decision" and anchor_id not in {d["decision"] for d in packet["decisions"]}:
        return [f"{where} names decision {anchor_id!r}, which doesn't govern this area"]
    if kind == "convention":
        path, _, slug = str(anchor_id).partition("#")
        known = {c["path"]: c["sections"] for c in packet["conventions"]}
        if path not in known:
            return [f"{where} names {path!r}, which isn't one of the packet's conventions"]
        if slug not in known[path]:
            return [f"{where} names section {slug!r}, which {path} doesn't have"]
    return []


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _tier(finding: Mapping[str, Any]) -> str | None:
    category = finding["category"]
    if category == "deviation":
        return "rule_deviations" if finding["anchor"]["kind"] == "rule" else "record_deviations"
    return {"decision_needed": "decisions_needed", "ambiguity": "ambiguities"}.get(category)


def _rank(finding: Mapping[str, Any]) -> tuple[int, str, str]:
    """Within a tier: more evidence sites first, then the anchor, then the text."""
    return (-len(finding.get("evidence", [])), str(finding["anchor"]["id"]), finding["problem"])


def report(
    packet: Mapping[str, Any],
    findings: Sequence[Mapping[str, Any]],
    root: Path | None = None,
    symbols: review.Symbols | None = None,
) -> dict[str, Any]:
    """The ranked report: the packet's mechanical findings with the reviewer's valid ones.

    A reviewer finding that fails :func:`problems`, or repeats another's
    identity (:func:`.review.finding_key`), is listed under ``rejected`` with
    why, never shown.
    """
    rejected = []
    shown: list[Mapping[str, Any]] = list(packet.get("findings", []))
    seen = {review.finding_key(f) for f in shown}
    for i, finding in enumerate(findings):
        found = problems(finding, packet, root, symbols)
        if not found:
            key = review.finding_key(finding)
            if key in seen:
                found = ["repeats another finding's area, outcome, anchor and evidence"]
            else:
                seen.add(key)
        if found:
            rejected.append({"index": i, "problems": found})
        else:
            shown.append(finding)
    tiers: dict[str, list[Mapping[str, Any]]] = {t: [] for t in TIERS}
    adherence = []
    for finding in shown:
        tier = _tier(finding)
        if tier is None:
            adherence.append(finding)
        else:
            tiers[tier].append(finding)
    return {
        "area": packet["area"]["id"],
        **{t: sorted(tiers[t], key=_rank) for t in TIERS},
        "adherence": {"count": len(adherence), "findings": sorted(adherence, key=_rank)},
        "unverified_rules": list(packet.get("unverified_rules", [])),
        "unresolved_sites": list(packet.get("unresolved_sites", [])),
        "unassigned": list(packet.get("unassigned", [])),
        "gaps": dict(packet.get("gaps", {})),
        "notes": list(packet.get("notes", [])),
        "rejected": rejected,
    }


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    """``python -m pyeye.docs_facts architecture plan|validate|report``. Prints JSON.

    - ``plan AREA [--decisions-dir D] [--convention PATH ...]``: the packet.
    - ``validate FINDINGS --packet PACKET``: each invalid finding's problems;
      exit 1 when any.
    - ``report FINDINGS --packet PACKET``: the ranked report.
    """
    parser = argparse.ArgumentParser(
        prog="docs_facts architecture",
        description="Review an area against its recorded architecture (#1132).",
    )
    parser.add_argument("--root", type=Path, default=root or Path.cwd(), help="repository root")
    sub = parser.add_subparsers(dest="action", required=True)
    plan_p = sub.add_parser("plan", help="the area's packet, with the mechanical findings")
    plan_p.add_argument(
        "area", help="an area ID from the structure kind's areas, or a module prefix"
    )
    plan_p.add_argument("--decisions-dir", type=Path, help="default: docs/decisions/entries")
    plan_p.add_argument(
        "--convention",
        action="append",
        default=[],
        metavar="PATH",
        help="a convention document read as a prose anchor, e.g. AGENTS.md (repeatable)",
    )
    for action in ("validate", "report"):
        p = sub.add_parser(action, help=f"{action} a reviewer's findings against the packet")
        p.add_argument("findings", type=Path, help="a JSON list of findings")
        p.add_argument("--packet", type=Path, required=True, help="the plan's packet")
    args = parser.parse_args(argv)
    base: Path = args.root
    try:
        if args.action == "plan":
            decisions_dir = (base / args.decisions_dir) if args.decisions_dir else None
            out: Any = plan(
                base, args.area, decisions_dir=decisions_dir, conventions=args.convention
            )
            code = 0
        else:
            packet, findings = _read(args.packet), _read(args.findings)
            symbols = review.project_symbols(base)
            if args.action == "validate":
                out = {
                    str(i): found
                    for i, f in enumerate(findings)
                    if (found := problems(f, packet, base, symbols))
                }
                code = 1 if out else 0
            else:
                out, code = report(packet, findings, base, symbols), 0
    except config.ConfigError as error:
        print(f"docs_facts architecture: {error}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, sort_keys=True))
    return code
