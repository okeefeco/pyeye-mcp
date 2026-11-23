#!/usr/bin/env python3
"""This repository's decision log: :mod:`pyeye.decisions` with its own settings (#1093).

The engine ships in the package (``python -m pyeye.decisions index|check|migrate``)
so every repo using the ``decision-log`` skill has it. This wrapper adds what is
this repo's alone: the entries grandfathered before ``Applies-to`` was required
(#636), the ``DECISIONS.md`` header ``migrate`` writes, and the command its
messages name.

It loads ``src/pyeye/decisions.py`` by file path, not ``import pyeye``: CI runs
it with a bare ``python`` (no project installed), and the ``pyeye`` package's
``__init__`` needs ``parso``. The module is stdlib only, which a test enforces.

Usage::

    decisions.py index [--symbol S] [--issue N] [--active] [--status STATUS]
    decisions.py check
    decisions.py migrate     # split entries still in DECISIONS.md into files
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "_pyeye_decisions", _ROOT / "src" / "pyeye" / "decisions.py"
)
assert _spec is not None and _spec.loader is not None
decisions = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = decisions  # dataclasses need the module registered
_spec.loader.exec_module(decisions)

DECISIONS_DIR = _ROOT / "docs" / "decisions"
ENTRIES_DIR = DECISIONS_DIR / "entries"
LOG_FILE = DECISIONS_DIR / "DECISIONS.md"
#: How this repo's messages name the command.
COMMAND = "python scripts/decisions.py"

#: Entries written before ``Applies-to`` became mandatory (#636) that don't have
#: one. They are grandfathered, with no back-fill. The list only shrinks: an
#: entry that gains ``Applies-to``, or is deleted, must leave it. Every entry
#: not listed here needs an ``Applies-to`` line.
APPLIES_TO_GRANDFATHERED: frozenset[str] = frozenset(
    {
        "2026-06-13-decision-log-fires-at-the-commit-checkpoint-not-ambient-ai.md",
        "2026-06-13-decision-log-ships-in-the-pyeye-plugin-not-claude-skills.md",
        "2026-06-13-decisions-captured-as-an-append-only-log-not-one-adr-file.md",
        "2026-06-16-397-ast-script-cache-cap-is-configurable-via-pyeye-artifact.md",
        "2026-06-16-397-ast-script-cache-stats-surfaced-in-the-performance-report.md",
        "2026-06-18-413-dev-tool-versions-black-ruff-mypy-single-sourced-in.md",
        "2026-06-18-414-dev-docs-deps-are-pep-735-dependency-groups-bare-uv-sync-is.md",
        "2026-06-20-422-subclasses-edge-becomes-single-hop-direct-only-conforming-to.md",
        "2026-06-20-423-outline-package-switches-to-submodules-survey-mode.md",
        "2026-06-20-426-relative-import-resolution-consolidated-onto-one-seam-with.md",
        "2026-06-21-423-submodules-count-expand-invariant-scoped-to-regular-packages.md",
        "2026-06-21-444-namespace-packages-anchored-through-resolve-inspect.md",
        "2026-06-21-445-expand-subclasses-stubs-are-ast-built-pointers-no-jedi-re.md",
        "2026-06-21-454-edge-stub-scope-reconciles-to-the-project-definition-site.md",
        "2026-06-21-458-in-band-bug-reporting-pointer-across-the-mcp-surface.md",
        "2026-06-22-462-git-state-hooks-are-pre-commit-managed-guard-on-pre-commit.md",
        "2026-06-23-358-outline-max-nodes-truncation-reserve-before-expand-member.md",
        "2026-06-23-481-uv-lockfile-is-authoritative-everywhere-pinned-per-context.md",
        "2026-06-27-457-search-all-scopes-resolves-via-the-ast-name-index-not-jedi.md",
        "2026-06-28-390-retire-the-workflows-mcp-resource-scheme-fold-dependency.md",
        "2026-06-28-488-trace-surfaces-interior-callee-resolution-loss-unresolved.md",
        "2026-06-28-488-trace-surfaces-unresolved-roots-as-an-always-present-honesty.md",
        "2026-06-28-489-reverse-references-are-a-sanctioned-lsp-handoff-not-a-dead.md",
        "2026-06-28-494-imports-edge-surfaces-unresolvable-imports-instead-of.md",
        "2026-06-29-492-architecture-review-rank-tier-comes-from-an-explicit-stakes.md",
        "2026-08-09-505-the-last-three-legacy-tools-were-removed-not-shipped.md",
        "2026-08-09-507-the-project-scan-excludes-nested-git-worktrees-not.md",
        "2026-10-29-396-shipped-prose-may-not-show-an-unmeasured-edge-inside-edge.md",
        "2026-10-29-506-dotted-handles-are-placed-by-definition-lookup-never-by.md",
        "2026-10-29-509-shipped-prose-is-guarded-against-teaching-removed-tools-core.md",
        "2026-10-29-545-inspect-outline-expand-return-one-explicit-not-found-shape.md",
        "2026-10-29-547-every-python-pre-commit-hook-runs-via-uv-run-frozen-only-non.md",
        "2026-10-29-555-plugin-tools-register-under-their-register-tools-keys-a.md",
        "2026-11-07-474-outline-defaults-to-depth-1-for-every-root-kind-max-depth.md",
        "2026-11-07-513-remove-configure-packages-standalone-scan-options-rather.md",
        "2026-11-07-573-local-env-setup-uses-uv-sync-frozen-not-bare-uv-sync.md",
        "2026-11-08-559-plugin-tools-resolve-scope-from-scope-defaults-keyed-on-mcp.md",
        "2026-11-08-596-package-survey-marks-unwalked-modules-survey-leaf-with-no.md",
        "2026-11-08-599-outline-counts-are-named-for-their-edge-and-mirror-inspect.md",
        "2026-11-08-608-worktree-hook-declares-its-environment-and-requires-uv.md",
        "2026-11-15-629-v2-x-release-classification-contract-conforming-corrections.md",
    }
)

STATIC_HEADER = "# Decision Log\n\nContract- or invariant-significant, friction-driven decisions. Each one is a small, verifiable fact: **Friction · Decision · Anchor** (stable references) **· Applies-to** (every governed site, or `none (<why>)`; required since #636) **· Verify** (checkable, or honestly labelled).\n\n**One file per decision** lives in [`entries/`](entries/), named `YYYY-MM-DD-<issue>-<slug>.md`. There is no committed index (#679). List and filter the entries from their front matter instead:\n\n```bash\npython scripts/decisions.py index                     # every entry, newest first\npython scripts/decisions.py index --active            # hide superseded entries\npython scripts/decisions.py index --symbol resolve_handle\npython scripts/decisions.py index --issue 626\npython scripts/decisions.py check                     # validate (also runs in CI)\n```\n\nRead the index first, then open the one to three entries that matter. An entry's `status` is `active`, `amended` or `superseded`. Its `amends` / `supersedes` / `amended_by` / `superseded_by` front matter links to the related entry files.\n\nNew entries are written with the `decision-log` skill (`.claude/skills/decision-log/SKILL.md`). This file is a static header and should almost never change.\n"


def main(argv: list[str] | None = None) -> int:
    """Run :func:`pyeye.decisions.main` with this repository's settings."""
    return decisions.main(
        argv,
        decisions_dir=DECISIONS_DIR,
        grandfathered=APPLIES_TO_GRANDFATHERED,
        header=STATIC_HEADER,
        command=COMMAND,
    )


if __name__ == "__main__":
    sys.exit(main())
