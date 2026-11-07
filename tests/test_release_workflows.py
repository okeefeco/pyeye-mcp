"""Contract tests for the release-PR → auto-tag → publish pipeline (#583).

These pin the GitHub Actions behaviour the design relies on, so a later edit
can't silently break releases:

* tags pushed with ``GITHUB_TOKEN`` don't trigger ``on: push`` workflows, so
  ``tag-release.yml`` must *dispatch* ``release.yml`` (``workflow_dispatch``
  always creates a run);
* PyPI trusted publishing doesn't support reusable workflows, so
  ``release.yml`` must not be called with ``uses:``;
* release notes come from the CHANGELOG, not only ``--generate-notes``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _load(name: str) -> dict:
    data = yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))
    # PyYAML parses the bare key `on` as boolean True.
    data["on"] = data.pop(True, data.get("on"))
    return data


def _run_text(workflow: dict) -> str:
    return "\n".join(
        step.get("run", "") for job in workflow["jobs"].values() for step in job.get("steps", [])
    )


class TestTagRelease:
    def test_triggers_only_on_changelog_changes_to_main(self):
        on = _load("tag-release.yml")["on"]
        assert set(on) == {"push"}
        assert on["push"] == {"branches": ["main"], "paths": ["CHANGELOG.md"]}

    def test_permissions_are_exactly_tag_and_dispatch(self):
        assert _load("tag-release.yml")["permissions"] == {"contents": "write", "actions": "write"}

    def test_decides_via_changelog_tool_with_subject_from_env(self):
        wf = _load("tag-release.yml")
        steps = wf["jobs"]["tag"]["steps"]
        decide = next(s for s in steps if s.get("id") == "decide")
        assert "scripts/changelog.py pending-release" in decide["run"]
        # The whole message, not just the subject: a merge commit carries the
        # PR title on its third line (#585).
        assert '--head-message "$HEAD_MESSAGE"' in decide["run"]
        # The commit message is attacker-influenced text: env only, never inline.
        assert "HEAD_MESSAGE" in decide["env"]
        assert "github.event.head_commit.message" not in decide["run"]

    def test_fetches_tags(self):
        steps = _load("tag-release.yml")["jobs"]["tag"]["steps"]
        checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout"))
        assert checkout["with"]["fetch-depth"] == 0

    def test_tags_then_dispatches_release_on_the_tag(self):
        run = _run_text(_load("tag-release.yml"))
        assert 'git tag -a "v$VERSION"' in run
        assert 'git push origin "v$VERSION"' in run
        assert 'gh workflow run release.yml --ref "v$VERSION"' in run
        assert run.index("git push origin") < run.index("gh workflow run")


class TestReleaseWorkflow:
    def test_runs_top_level_on_tags_and_dispatch(self):
        on = _load("release.yml")["on"]
        assert "workflow_dispatch" in on
        assert on["push"]["tags"] == ["v*"]
        assert "workflow_call" not in on

    def test_never_called_as_a_reusable_workflow(self):
        for path in _WORKFLOWS.glob("*.y*ml"):
            for job in (_load(path.name).get("jobs") or {}).values():
                assert "release.yml" not in str(job.get("uses", "")), path.name

    def test_release_notes_come_from_the_changelog(self):
        run = _run_text(_load("release.yml"))
        assert "scripts/changelog.py notes" in run
        assert "--notes-file release-notes.md" in run

    def test_validate_job_requires_a_changelog_section(self):
        steps = _load("release.yml")["jobs"]["validate"]["steps"]
        assert any("scripts/changelog.py notes" in s.get("run", "") for s in steps)


def test_ci_checks_the_changelog_with_tags():
    job = _load("ci.yml")["jobs"]["changelog-validation"]
    checkout = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout"))
    assert checkout["with"]["fetch-depth"] == 0
    assert any("scripts/changelog.py check" in s.get("run", "") for s in job["steps"])
