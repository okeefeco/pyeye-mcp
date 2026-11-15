#!/usr/bin/env python3
"""pyeye-verify round-trip probe: do emitted handles resolve again? (#616).

Runs ``expand(<module>, "imports")`` against a project, then feeds every
emitted stub's handle back into ``inspect`` and ``resolve`` and counts the ones
that don't round-trip:

* ``inspect_miss`` / ``resolve_miss`` — the tool reports ``found: false``;
* ``disagree`` — one tool finds it and the other doesn't;
* ``handle_mismatch`` — both find it but return a different canonical handle.

It measures, it doesn't judge: it always exits 0 (except on a usage error or an
``expand`` that itself fails). The pyeye-verify skill records the counts as a
scenario baseline row. The pytest-side sweep over fixtures and ``src/pyeye``,
with an allow-list, is ``test_emitted_handles_round_trip`` (#614); this probe is
its counterpart on real scenario repos at pinned commits.

The build under test is whatever ``pyeye`` this interpreter imports, so run it
with ``uv run`` from the checkout whose build you are verifying.

Usage:
    roundtrip_probe.py <project_path> <module> [--json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RoundTripResult:
    """Counts (and examples) of emitted handles that fail to round-trip."""

    project_path: str
    module: str
    stubs: int = 0
    inspect_miss: list[str] = field(default_factory=list)
    resolve_miss: list[str] = field(default_factory=list)
    disagree: list[str] = field(default_factory=list)
    handle_mismatch: list[str] = field(default_factory=list)
    miss_scopes: dict[str, int] = field(default_factory=dict)

    @property
    def not_round_tripping(self) -> int:
        """Distinct handles that fail any of the four checks."""
        return len(
            set(self.inspect_miss)
            | set(self.resolve_miss)
            | set(self.disagree)
            | set(self.handle_mismatch)
        )


async def probe(project_path: str, module: str, analyzer: Any | None = None) -> RoundTripResult:
    """Run the round-trip probe for *module* in the project at *project_path*.

    Raises ``RuntimeError`` when ``expand`` itself reports the module not found:
    a probe with zero stubs because the input was wrong must not look like a
    clean pass.
    """
    from pyeye.mcp.operations.expand import expand
    from pyeye.mcp.operations.inspect import inspect
    from pyeye.mcp.operations.resolve import resolve

    if analyzer is None:
        from pyeye.project_manager import ProjectManager

        analyzer = ProjectManager().get_analyzer(project_path)

    expanded = await expand(module, "imports", analyzer)
    if expanded.get("found") is False:
        raise RuntimeError(f"expand({module!r}, 'imports') reported not found: {expanded!r}")

    result = RoundTripResult(project_path=project_path, module=module)
    seen: dict[str, str] = {}
    for stub in expanded.get("stubs") or []:
        seen.setdefault(stub["handle"], stub.get("scope") or "unknown")
    result.stubs = len(seen)

    for handle, scope in seen.items():
        inspected = await inspect(handle, analyzer)
        resolved = await resolve(handle, analyzer)
        i_found = inspected.get("found", True) is not False
        r_found = resolved.get("found") is True
        if not i_found:
            result.inspect_miss.append(handle)
        if not r_found:
            result.resolve_miss.append(handle)
        if i_found != r_found:
            result.disagree.append(handle)
        elif i_found and inspected.get("handle") != resolved.get("handle"):
            result.handle_mismatch.append(handle)
        if not (i_found and r_found):
            result.miss_scopes[scope] = result.miss_scopes.get(scope, 0) + 1
    return result


def format_summary(result: RoundTripResult) -> str:
    """One baseline-row-sized summary plus up to five example handles per bucket."""
    lines = [
        f"round-trip probe: expand({result.module!r}, imports) -> {result.stubs} stub(s); "
        f"{result.not_round_tripping} don't round-trip "
        f"(inspect miss {len(result.inspect_miss)}, resolve miss {len(result.resolve_miss)}, "
        f"disagree {len(result.disagree)}, handle mismatch {len(result.handle_mismatch)})"
    ]
    if result.miss_scopes:
        scopes = ", ".join(f"{k}={v}" for k, v in sorted(result.miss_scopes.items()))
        lines.append(f"  misses by stub scope: {scopes}")
    for label in ("inspect_miss", "resolve_miss", "disagree", "handle_mismatch"):
        handles = getattr(result, label)
        if handles:
            lines.append(f"  {label}: {', '.join(handles[:5])}{' …' if len(handles) > 5 else ''}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("project_path")
    parser.add_argument("module", help="dotted module name to expand(imports) from")
    parser.add_argument("--json", action="store_true", help="emit the full result as JSON")
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(probe(args.project_path, args.module))
    except RuntimeError as exc:
        print(f"round-trip probe: {exc}", file=sys.stderr)
        return 2
    if args.json:
        payload = asdict(result) | {"not_round_tripping": result.not_round_tripping}
        print(json.dumps(payload, indent=2))
    else:
        print(format_summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
