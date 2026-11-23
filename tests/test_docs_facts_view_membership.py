"""A view losing a member reaches the change-triggered review (#1114).

Ruled (a): each snapshot file records every view's members, so the base side of
a diff knows which views held a fact that has since gone, with no git in the
engine. A removed member maps to its old views' pages, and the view is listed
under "Views that lost a member". With the family in its own snapshot file
(#1108) as well as in ``facts.json``.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from pyeye.docs_facts import changed, cli, config
from pyeye.docs_facts.docs import DocEntry
from pyeye.docs_facts.facts import Bindable, Fact, memberships, view
from pyeye.docs_facts.registry import Extractor
from pyeye.docs_facts.setup import Setup
from tests.test_docs_facts_reference_only import (
    ARCH,
    EXTRACTORS,
    VIEW_PAGE,
    _commit,
    _foreign,
    _with_view,
)


def _setup(tmp_path: Path, *, own_file: bool) -> tuple[Path, Setup]:
    root, setup = _foreign(tmp_path, snapshots={"arch": ARCH} if own_file else None)
    (root / "app/b.py").write_text("Y = 2\n", encoding="utf-8")
    (root / VIEW_PAGE).write_text(
        "# Modules\n\n<!-- fact:begin arch.modules --><!-- fact:end -->\n", encoding="utf-8"
    )
    page = DocEntry(VIEW_PAGE, "human", "prose", MappingProxyType({}))
    return root, dataclasses.replace(
        setup,
        extractors=(EXTRACTORS[0], Extractor("arch", ("arch",), _with_view), EXTRACTORS[2]),
        docs=(*setup.docs, page),
    )


class TestTheSnapshotRecordsViews:
    def test_memberships(self) -> None:
        a, b = Fact("x.a", 1, "1"), Fact("x.b", 2, "2")
        facts: dict[str, Bindable] = {"x.a": a, "x.b": b, "x.all": view("x.all", [b, a], "")}

        assert memberships(facts) == {"x.all": ["x.b", "x.a"]}  # display order kept

    @pytest.mark.parametrize("own_file", [False, True])
    def test_each_view_is_recorded_in_its_familys_file(
        self, tmp_path: Path, own_file: bool
    ) -> None:
        root, setup = _setup(tmp_path, own_file=own_file)

        result = cli.plan(root, setup=setup)

        where = ARCH if own_file else setup.paths.snapshot
        views: dict[str, Any] = json.loads(result.outputs[where])["views"]
        assert views == {"arch.modules": ["arch.members.app.a", "arch.members.app.b"]}
        if own_file:
            assert json.loads(result.outputs[setup.paths.snapshot])["views"] == {}

    def test_pyeyes_own_snapshot_records_its_views(self) -> None:
        data = json.loads(Path(config.load(Path(".")).paths.snapshot).read_text(encoding="utf-8"))

        assert "determinism.ast" in data["views"]["determinism.table"]


class TestDiff:
    def test_a_view_that_lost_a_member_maps_the_member_to_its_pages(self) -> None:
        found = changed.diff(
            {"x.a": 1, "x.b": 2},
            {"x.a": 1},
            {"x.all": ["p.md"], "x.a": ["p.md"]},
            base_views={"x.all": ["x.a", "x.b"]},
            head_views={"x.all": ["x.a"]},
        )

        assert (found.removed, found.shrunk, found.grown) == (["x.b"], ["x.all"], [])
        assert found.pages == {"x.b": ["p.md"], "x.all": ["p.md"]}
        text = changed.summary(found, "base")
        assert "**Views that lost a member** (1)" in text
        assert "- `x.b` (bound in p.md)" in text

    def test_a_member_moved_between_views_is_both(self) -> None:
        """No fact changes, yet both views' pages need a look."""
        found = changed.diff(
            {"x.a": 1},
            {"x.a": 1},
            {},
            base_views={"x.one": ["x.a"], "x.two": []},
            head_views={"x.one": [], "x.two": ["x.a"]},
        )

        assert (found.grown, found.shrunk) == (["x.two"], ["x.one"])
        assert "No fact changed." not in changed.summary(found, "base")

    def test_a_base_without_memberships_sees_gains_only(self) -> None:
        """A base snapshot from before #1114: no loss can be seen, and nothing breaks."""
        found = changed.diff(
            {"x.a": 1, "x.b": 2}, {"x.a": 1, "x.c": 3}, {}, head_views={"x.all": ["x.a", "x.c"]}
        )

        assert (found.grown, found.shrunk) == (["x.all"], [])


class TestEndToEnd:
    @pytest.mark.parametrize("own_file", [False, True])
    def test_changed_lists_the_view_and_the_gone_members_page(
        self, tmp_path: Path, own_file: bool, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, setup = _setup(tmp_path, own_file=own_file)
        assert cli.generate(root, setup=setup) == 0
        _commit(root)
        (root / "app/b.py").unlink()
        assert cli.generate(root, setup=setup) == 0
        capsys.readouterr()

        assert cli.report_changed(root, "HEAD", setup=setup) == 0

        out = capsys.readouterr().out
        assert "**Views that lost a member** (1)" in out
        assert f"- `arch.modules` (bound in {VIEW_PAGE})" in out
        assert f"- `arch.members.app.b` (bound in {VIEW_PAGE})" in out

    def test_a_base_from_before_the_memberships_still_works(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, setup = _setup(tmp_path, own_file=False)
        assert cli.generate(root, setup=setup) == 0
        snapshot = root / setup.paths.snapshot
        old = json.loads(snapshot.read_text(encoding="utf-8"))
        snapshot.write_text(json.dumps({"facts": old["facts"]}), encoding="utf-8")
        _commit(root)
        assert cli.generate(root, setup=setup) == 0
        capsys.readouterr()

        assert cli.report_changed(root, "HEAD", setup=setup) == 0
        assert "lost a member" not in capsys.readouterr().out


class TestTheReviewScope:
    def test_picks_the_pages_of_a_view_that_lost_a_member(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On pyeye's own docs: ``determinism.table`` loses a (made-up) member."""
        from pyeye.docs_facts import registry, review

        facts = registry.build(Path("."))
        paths = config.load(Path(".")).paths
        head = cli._committed_snapshots(Path("."), paths)
        views = cli._committed_views(Path("."), paths)
        gone = "determinism.retired"
        before = {**head, gone: "a tier that no longer exists"}
        old_views = {**views, "determinism.table": [*views["determinism.table"], gone]}
        monkeypatch.setattr(cli, "base_snapshots", lambda _r, _b, _p: dict(before))
        monkeypatch.setattr(cli, "base_views", lambda _r, _b, _p: dict(old_views))
        monkeypatch.setattr(cli, "_committed_snapshots", lambda _r, _p: dict(head))
        monkeypatch.setattr(cli, "_committed_views", lambda _r, _p: dict(views))

        out = review.scope(Path("."), facts, base="HEAD")

        assert "determinism.table" in out["changed"]
        assert "docs/architecture/resolution.md" in {p["page"] for p in out["pages"]}
