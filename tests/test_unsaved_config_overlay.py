"""Unsaved ``configure_packages`` calls accumulate for the session (#953).

Every call rebuilt ``ProjectConfig`` from disk and appended only its own entries,
so a second ``save=False`` call silently dropped the first one's, from the
analyzer too. The maintainer's ruling:

- a per-project, process-wide OVERLAY of unsaved additions, applied by every
  ``ProjectConfig`` load after the disk sources, merged as a save merges
  (packages and standalone dirs extend, deduped; a namespace replaces its list);
- a ``save=True`` call persists the overlay with its own entries, even with none
  of its own, then clears the overlay; a restart drops it;
- the response's always-present ``unsaved`` lists what lives only in the
  overlay, shaped like the response's own ``packages`` / ``namespaces`` /
  ``standalone`` so each compares with its counterpart.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from pyeye.config import ProjectConfig

EMPTY = {"packages": [], "namespaces": {}, "standalone": {"dirs": []}}


@pytest.fixture
def workspace(tmp_path: Path) -> dict[str, Path]:
    """A project and five directories to configure, kept away from its siblings.

    Sibling auto-discovery would otherwise configure ``libA``/``libB`` from disk
    already (they hold ``.py`` files), so they would never be "unsaved".
    """
    dirs = {"proj": tmp_path / "proj"}
    for name in ("libA", "libB", "ns1", "ns2", "scripts"):
        dirs[name] = tmp_path / "elsewhere" / name
    for path in dirs.values():
        path.mkdir(parents=True)
    (dirs["proj"] / "app.py").write_text("", encoding="utf-8")
    (dirs["libA"] / "alpha.py").write_text("class Alpha:\n    pass\n", encoding="utf-8")
    (dirs["libB"] / "beta.py").write_text("class Beta:\n    pass\n", encoding="utf-8")
    return dirs


def _configure(proj: Path, **args: Any) -> dict[str, Any]:
    from pyeye.mcp.server import mcp

    result = asyncio.run(
        mcp.call_tool("configure_packages", {**args, "project_path": proj.as_posix()})
    )
    assert not result.is_error, result.content
    payload = result.structured_content
    assert isinstance(payload, dict)
    return payload


def _posix(*paths: Path) -> list[str]:
    return [p.resolve().as_posix() for p in paths]


class TestAccumulation:
    def test_two_unsaved_calls_keep_both_packages(self, workspace: dict[str, Path]) -> None:
        proj = workspace["proj"]
        _configure(proj, packages=[workspace["libA"].as_posix()], save=False)
        second = _configure(proj, packages=[workspace["libB"].as_posix()], save=False)

        assert second["packages"][1:] == _posix(workspace["libA"], workspace["libB"])
        assert second["unsaved"]["packages"] == _posix(workspace["libA"], workspace["libB"])
        assert not (proj / ".pyeye.json").exists()

    def test_the_analyzer_sees_the_earlier_call_too(self, workspace: dict[str, Path]) -> None:
        """The first call's package didn't vanish from analysis either."""
        from pyeye.mcp.server import mcp

        proj = workspace["proj"]
        _configure(proj, packages=[workspace["libA"].as_posix()], save=False)
        _configure(proj, packages=[workspace["libB"].as_posix()], save=False)

        for handle in ("alpha.Alpha", "beta.Beta"):
            result = asyncio.run(
                mcp.call_tool("resolve", {"identifier": handle, "project_path": proj.as_posix()})
            )
            assert result.structured_content["found"] is True, handle

    def test_merged_as_a_save_merges(self, workspace: dict[str, Path]) -> None:
        proj = workspace["proj"]
        a, ns1, ns2, scripts = (workspace[k].as_posix() for k in ("libA", "ns1", "ns2", "scripts"))
        _configure(
            proj, packages=[a], namespaces={"co": [ns1]}, standalone_dirs=[scripts], save=False
        )
        last = _configure(
            proj, packages=[a], namespaces={"co": [ns2]}, standalone_dirs=[scripts], save=False
        )

        assert last["packages"].count(workspace["libA"].resolve().as_posix()) == 1  # deduped
        assert last["namespaces"] == {"co": _posix(workspace["ns2"])}  # replaced per name
        assert last["standalone"]["dirs"] == [scripts]  # extended, deduped

    def test_projects_have_their_own_overlay(
        self, workspace: dict[str, Path], tmp_path: Path
    ) -> None:
        other = tmp_path / "other"
        other.mkdir()
        _configure(workspace["proj"], packages=[workspace["libA"].as_posix()], save=False)

        assert _configure(other, save=False)["unsaved"] == EMPTY


class TestSave:
    def test_a_save_persists_the_overlay_with_its_own_entries(
        self, workspace: dict[str, Path]
    ) -> None:
        proj = workspace["proj"]
        _configure(proj, packages=[workspace["libA"].as_posix()], save=False)
        saved = _configure(proj, packages=[workspace["libB"].as_posix()], save=True)

        on_disk = json.loads((proj / ".pyeye.json").read_text(encoding="utf-8"))
        assert on_disk["packages"] == [workspace["libA"].as_posix(), workspace["libB"].as_posix()]
        assert saved["unsaved"] == EMPTY

    def test_a_bare_save_persists_a_pending_overlay(self, workspace: dict[str, Path]) -> None:
        proj = workspace["proj"]
        _configure(proj, packages=[workspace["libA"].as_posix()], save=False)
        saved = _configure(proj, save=True)

        on_disk = json.loads((proj / ".pyeye.json").read_text(encoding="utf-8"))
        assert on_disk["packages"] == [workspace["libA"].as_posix()]
        assert saved["unsaved"] == EMPTY
        assert _configure(proj, save=False)["unsaved"] == EMPTY  # cleared

    def test_a_bare_save_with_nothing_pending_writes_nothing(
        self, workspace: dict[str, Path]
    ) -> None:
        _configure(workspace["proj"], save=True)

        assert not (workspace["proj"] / ".pyeye.json").exists()


class TestOverDisk:
    def test_a_reloaded_config_gets_the_overlay_on_top(self, workspace: dict[str, Path]) -> None:
        proj = workspace["proj"]
        _configure(proj, packages=[workspace["libA"].as_posix()], save=False)
        (proj / ".pyeye.json").write_text(
            json.dumps({"packages": [workspace["libB"].as_posix()]}), encoding="utf-8"
        )

        config = ProjectConfig(proj.as_posix())

        assert set(_posix(workspace["libA"], workspace["libB"])) <= set(config.get_package_paths())

    def test_an_entry_that_reaches_the_file_is_no_longer_unsaved(
        self, workspace: dict[str, Path]
    ) -> None:
        proj = workspace["proj"]
        _configure(proj, packages=[workspace["libA"].as_posix()], save=False)
        (proj / ".pyeye.json").write_text(
            json.dumps({"packages": [workspace["libA"].as_posix()]}), encoding="utf-8"
        )

        assert _configure(proj, save=False)["unsaved"] == EMPTY

    def test_the_disk_only_view_leaves_the_overlay_out(self, workspace: dict[str, Path]) -> None:
        proj = workspace["proj"]
        _configure(proj, packages=[workspace["libA"].as_posix()], save=False)

        disk = ProjectConfig(proj.as_posix(), include_unsaved=False)

        assert workspace["libA"].resolve().as_posix() not in disk.get_package_paths()


class TestUnsavedKey:
    def test_it_is_always_present_and_empty_when_nothing_is_unsaved(
        self, workspace: dict[str, Path]
    ) -> None:
        assert _configure(workspace["proj"], save=False)["unsaved"] == EMPTY

    def test_it_mirrors_the_responses_own_fields(self, workspace: dict[str, Path]) -> None:
        proj = workspace["proj"]
        payload = _configure(
            proj,
            packages=[workspace["libA"].as_posix()],
            namespaces={"co": [workspace["ns1"].as_posix()]},
            standalone_dirs=[workspace["scripts"].as_posix()],
            save=False,
        )
        unsaved = payload["unsaved"]

        assert set(unsaved) == {"packages", "namespaces", "standalone"}
        assert set(unsaved["packages"]) <= set(payload["packages"])
        assert unsaved["namespaces"]["co"] == payload["namespaces"]["co"]
        assert unsaved["standalone"]["dirs"] == payload["standalone"]["dirs"]


class TestSequenceExamples:
    """The docs-example syntax that executes the accumulation in CI (#953, #828)."""

    def test_an_array_body_is_a_sequence(self) -> None:
        from pyeye.docs_facts.examples import parse_examples

        text = (
            "```json pyeye-example tool=configure_packages\n"
            '[{"packages": ["a"], "save": false}, {"packages": ["b"], "save": false}]\n'
            "```\n"
        )
        examples, problems = parse_examples(text)

        assert problems == []
        assert examples[0].before == ({"packages": ["a"], "save": False},)
        assert examples[0].args == {"packages": ["b"], "save": False}

    @pytest.mark.parametrize(
        "body", ["[]", '[{"save": false}, 3]', '[{"save": false}, {"project_path": "x"}]']
    )
    def test_a_bad_sequence_is_a_problem(self, body: str) -> None:
        from pyeye.docs_facts.examples import parse_examples

        examples, problems = parse_examples(
            f"```json pyeye-example tool=configure_packages\n{body}\n```\n"
        )

        assert examples == []
        assert len(problems) == 1
