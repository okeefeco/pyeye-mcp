"""``superclasses`` says WHY a base is unresolved (#1065, ruled 2026-11-21).

``unresolved_superclass_details`` is always present on the ``superclasses``
edge and nowhere else. It is parallel to ``unresolved_superclasses``, in the
same order, ``details[i]["base"] == unresolved_superclasses[i]``. Each entry is
``{base, reason}``. An ``ambiguous`` entry also carries ``candidates`` (the
handles, sorted) and ``candidate_count`` (every distinct target). A target in a
restricted directory, or one with no handle, is counted but never listed.

The reason comes from the one base lookup (``pyeye.resolver.base_class_lookup``,
which ``base_class_target`` and so the class graph use, #1057). So the lookup
that decides resolved-or-not also says why.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye import resolver
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand

KIDS = """import _thread

from .shim import Local


def make():
    return object


def func():
    pass


class NotAName(make()):
    pass


class Missing(Undefined):  # noqa: F821
    pass


class Shim(Local):
    pass


class NotAClass(func):
    pass


class CModule(_thread._local):
    pass


class Mixed(object, Local, make()):
    pass


class Resolved(object):
    pass


def f():
    class Outer:
        class Inner:
            pass

    class LocalMember(Outer.Inner):
        pass

    return LocalMember


def g(X):
    class X:
        pass

    class LocalParam(X):
        pass

    return LocalParam
"""

FILES = {
    "pkg/__init__.py": "",
    "pkg/_fast.py": "class Local:\n    pass\n",
    "pkg/_slow.py": "class Local:\n    pass\n",
    "pkg/shim.py": (
        "try:\n    from ._fast import Local\nexcept ImportError:\n    from ._slow import Local\n"
    ),
    "pkg/kids.py": KIDS,
}


@pytest.fixture
def analyzer(tmp_path: Path) -> JediAnalyzer:
    for rel, text in FILES.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return JediAnalyzer(tmp_path.as_posix())


async def _edge(analyzer: JediAnalyzer, cls: str) -> dict[str, Any]:
    return dict(await expand(f"pkg.kids.{cls}", "superclasses", analyzer))


class TestEachReason:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("cls", "base", "reason"),
        [
            ("NotAName", "make()", "not_a_name"),
            ("Missing", "Undefined", "unresolvable"),
            ("NotAClass", "func", "not_a_class"),
            # Jedi sees no definition of a C module's class in pyeye's environment.
            ("CModule", "_thread._local", "unresolvable"),
            # Found, but the parameter binds X too, so the class has no unique
            # handle (#1049, #1071). A class in a local class is named (#1025).
            ("g.LocalParam", "X", "no_handle"),
        ],
    )
    async def test_the_reason(
        self, analyzer: JediAnalyzer, cls: str, base: str, reason: str
    ) -> None:
        result = await _edge(analyzer, cls)

        assert result["unresolved_superclasses"] == [base]
        assert result["unresolved_superclass_details"] == [{"base": base, "reason": reason}]

    @pytest.mark.asyncio
    async def test_ambiguous_lists_the_candidates_sorted(self, analyzer: JediAnalyzer) -> None:
        result = await _edge(analyzer, "Shim")

        assert result["unresolved_superclass_details"] == [
            {
                "base": "Local",
                "reason": "ambiguous",
                "candidates": ["pkg._fast.Local", "pkg._slow.Local"],
                "candidate_count": 2,
            }
        ]

    @pytest.mark.asyncio
    async def test_restricted(
        self, analyzer: JediAnalyzer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A sole restricted target: the reason only, no location disclosed (#999)."""
        real = resolver.in_restricted_dir
        monkeypatch.setattr(
            resolver,
            "in_restricted_dir",
            lambda name: "_fast" in str(getattr(name, "module_path", "")) or real(name),
        )
        (Path(analyzer.project_path) / "pkg/kids.py").write_text(
            KIDS + "\n\nfrom ._fast import Local as Fast\n\n\nclass Secret(Fast):\n    pass\n",
            encoding="utf-8",
        )

        result = await _edge(analyzer, "Secret")

        assert result["unresolved_superclass_details"] == [{"base": "Fast", "reason": "restricted"}]

    @pytest.mark.asyncio
    async def test_a_restricted_candidate_is_counted_never_listed(
        self, analyzer: JediAnalyzer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = resolver.in_restricted_dir
        monkeypatch.setattr(
            resolver,
            "in_restricted_dir",
            lambda name: "_fast" in str(getattr(name, "module_path", "")) or real(name),
        )

        result = await _edge(analyzer, "Shim")

        (detail,) = result["unresolved_superclass_details"]
        assert detail["reason"] == "ambiguous"
        assert detail["candidates"] == ["pkg._slow.Local"]
        assert detail["candidate_count"] == 2  # count > len(candidates): one not shown


class TestTheContract:
    @pytest.mark.asyncio
    async def test_parallel_to_unresolved_superclasses_in_order(
        self, analyzer: JediAnalyzer
    ) -> None:
        result = await _edge(analyzer, "Mixed")

        assert [s["handle"] for s in result["stubs"]] == ["builtins.object"]
        assert result["unresolved_superclasses"] == ["Local", "make()"]
        assert [d["base"] for d in result["unresolved_superclass_details"]] == [
            "Local",
            "make()",
        ]
        assert [d["reason"] for d in result["unresolved_superclass_details"]] == [
            "ambiguous",
            "not_a_name",
        ]

    @pytest.mark.asyncio
    async def test_all_resolved_is_a_measured_empty_list(self, analyzer: JediAnalyzer) -> None:
        result = await _edge(analyzer, "Resolved")

        assert result["unresolved_superclasses"] == []
        assert result["unresolved_superclass_details"] == []

    @pytest.mark.asyncio
    async def test_only_ambiguous_carries_candidates(self, analyzer: JediAnalyzer) -> None:
        for cls in ("NotAName", "Missing", "NotAClass", "CModule", "f.LocalMember"):
            for detail in (await _edge(analyzer, cls))["unresolved_superclass_details"]:
                assert set(detail) == {"base", "reason"}, (cls, detail)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("edge", ["subclasses", "members", "callees", "imports"])
    async def test_absent_on_every_other_edge(self, analyzer: JediAnalyzer, edge: str) -> None:
        result = await expand("pkg.kids.Shim", edge, analyzer)

        assert "unresolved_superclass_details" not in result


class TestTheLookupIsShared:
    def test_base_class_target_is_the_lookups_target(self) -> None:
        """The class graph's resolution and the edge's reasons come from one lookup."""
        import ast

        tree = ast.parse("class C(make()):\n    pass\n")
        base = tree.body[0].bases[0]  # type: ignore[attr-defined]

        lookup = resolver.base_class_lookup(None, base)

        assert lookup.target is None and lookup.reason == "not_a_name"
        assert resolver.base_class_target(None, base) is None
