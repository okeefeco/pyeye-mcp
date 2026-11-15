"""Merge-queue contract for ``.github/workflows/ci.yml`` (#649).

With a merge queue, GitHub waits for every required status check to report on
the ``merge_group`` run. A required name that never reports leaves the queue
stuck, and one reported twice (a real job plus its docs-only dummy) is
ambiguous. This test evaluates each job's ``if:`` for the events the queue and
PRs produce, and checks that every required name reports **exactly once**.

The required names mirror the ``main`` ruleset. Changing either means changing
both.
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_CI = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"

REQUIRED_CHECKS = frozenset(
    {
        "pre-commit",
        "type-check",
        "changelog-validation",
        "changes",
        "security",
        "test-pr (ubuntu-latest, 3.11)",
        "test-pr (ubuntu-latest, 3.12)",
        "test-pr (ubuntu-latest, 3.13)",
        "test-pr (windows-latest, 3.11)",
        "test-pr (windows-latest, 3.13)",
        "test-pr (macos-latest, 3.13)",
    }
)


def _load() -> dict[str, Any]:
    data = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    # PyYAML reads the bare key `on` as boolean True.
    data["on"] = data.pop(True, data.get("on"))
    return data


def _evaluate(condition: str | None, context: dict[str, str]) -> bool:
    """Evaluate a job-level ``if:`` built from ==, !=, &&, || and parentheses."""
    if condition is None:
        return True
    expr = " ".join(condition.split())  # YAML block scalars span lines
    for name, value in sorted(context.items(), key=lambda kv: -len(kv[0])):
        expr = expr.replace(name, repr(value))
    expr = expr.replace("&&", " and ").replace("||", " or ")
    leftover = re.sub(r"'[^']*'|\b(and|or|not)\b|==|!=|[()\s]", "", expr)
    assert not leftover, f"unsupported expression in ci.yml if: {condition!r} -> {leftover!r}"
    return bool(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 - vetted above


def _job_names(job_id: str, job: dict[str, Any]) -> list[str]:
    """The check names a job reports: its ``name:`` expanded over its matrix."""
    template = job.get("name", job_id)
    matrix = job.get("strategy", {}).get("matrix")
    if not matrix:
        return [template]
    if "include" in matrix:
        combos = list(matrix["include"])
    else:
        keys = list(matrix)
        combos = [
            dict(zip(keys, vals, strict=True)) for vals in itertools.product(*matrix.values())
        ]
    names = []
    for combo in combos:
        if "name" not in job:
            # GitHub's default: "<job id> (<matrix values in order>)".
            names.append(f"{job_id} ({', '.join(str(v) for v in combo.values())})")
            continue
        name = template
        for key, value in combo.items():
            name = re.sub(r"\$\{\{\s*matrix\." + key + r"\s*\}\}", str(value), name)
        names.append(name)
    return names


def _reported(context: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job_id, job in _load()["jobs"].items():
        if _evaluate(job.get("if"), context):
            for name in _job_names(job_id, job):
                counts[name] = counts.get(name, 0) + 1
    return counts


_EVENTS = {
    "merge_group": {
        "github.event_name": "merge_group",
        "github.ref": "refs/heads/gh-readonly-queue/main/pr-1-abc",
        # What the `changes` job emits on any non-PR event.
        "needs.changes.outputs.code": "true",
        "needs.changes.outputs.docs": "false",
        "needs.changes.outputs.plugins": "true",
    },
    "pull_request (code)": {
        "github.event_name": "pull_request",
        "github.ref": "refs/pull/1/merge",
        "needs.changes.outputs.code": "true",
        "needs.changes.outputs.docs": "false",
        "needs.changes.outputs.plugins": "false",
    },
    "pull_request (docs only)": {
        "github.event_name": "pull_request",
        "github.ref": "refs/pull/1/merge",
        "needs.changes.outputs.code": "false",
        "needs.changes.outputs.docs": "true",
        "needs.changes.outputs.plugins": "false",
    },
}


def test_merge_group_trigger_present() -> None:
    assert "merge_group" in _load()["on"]


@pytest.mark.parametrize("event", sorted(_EVENTS))
def test_every_required_check_reports_exactly_once(event: str) -> None:
    counts = _reported(_EVENTS[event])
    missing = sorted(REQUIRED_CHECKS - counts.keys())
    duplicated = sorted(n for n in REQUIRED_CHECKS if counts.get(n, 0) > 1)
    assert not missing, f"{event}: required checks never reported: {missing}"
    assert not duplicated, f"{event}: required checks reported twice: {duplicated}"


def test_merge_group_runs_the_real_tests_not_the_dummies() -> None:
    context = _EVENTS["merge_group"]
    jobs = _load()["jobs"]
    assert _evaluate(jobs["test-pr"]["if"], context)
    assert _evaluate(jobs["type-check"]["if"], context)
    assert not _evaluate(jobs["test-pr-dummy"]["if"], context)
    assert not _evaluate(jobs["type-check-dummy"]["if"], context)
    # test-main stays push-to-main only; a queue ref never matches.
    assert not _evaluate(jobs["test-main"]["if"], context)


def test_changes_outputs_force_code_on_non_pr_events() -> None:
    """The ``changes`` outputs fall back to the forced non-PR step.

    They used to read only the paths-filter step, which doesn't run outside
    pull_request, so ``code`` was empty (not ``true``) on push and would have
    been on merge_group too.
    """
    changes = _load()["jobs"]["changes"]
    for key in ("code", "docs", "plugins"):
        assert "steps.non-pr.outputs." + key in changes["outputs"][key]
    non_pr = next(s for s in changes["steps"] if s.get("id") == "non-pr")
    assert non_pr["if"] == "github.event_name != 'pull_request'"
    assert 'echo "code=true"' in non_pr["run"]


def test_evaluator_rejects_unknown_expressions() -> None:
    with pytest.raises(AssertionError, match="unsupported"):
        _evaluate("contains(github.event.head_commit.message, 'x')", {})


def _test_step_env(job: str) -> str:
    steps = _load()["jobs"][job]["steps"]
    step = next(s for s in steps if s.get("name") == "Run tests with coverage")
    return str(step.get("env", {}).get("PYEYE_EXHAUSTIVE_PATHS", ""))


def test_merge_queue_runs_the_exhaustive_path_variants() -> None:
    """#775: the queue must test what push-to-main tests.

    test-main sets PYEYE_EXHAUSTIVE_PATHS off Windows; test-pr ran without it, so
    the queue passed PRs that turned main red for 15 merges.  test-pr now sets it
    on merge_group (off Windows, as test-main), and only there, so per-PR runs
    stay fast.
    """
    main_env = _test_step_env("test-main")
    pr_env = _test_step_env("test-pr")
    assert "matrix.os != 'windows-latest'" in main_env
    assert "github.event_name == 'merge_group'" in pr_env
    assert "matrix.os != 'windows-latest'" in pr_env
    assert "'1'" in pr_env
