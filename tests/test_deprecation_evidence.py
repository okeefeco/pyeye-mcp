"""``inspect`` reports a symbol's deprecation from static evidence only (#1082).

``deprecation`` is a list of evidence, present on a function, method or class
whose definition pyeye could read: ``[]`` when it was checked and nothing was
found, ABSENT when the check couldn't run or doesn't apply (absence-vs-zero).
Each entry is ``{"kind", "via", "line"}``:

- ``kind: "unconditional"``: a ``@deprecated`` decorator, or a
  ``warnings.warn(..., <deprecation category>)`` that runs on every call (a
  statement of the body, or of a class's ``__init__``, not under a branch);
- ``kind: "conditional"``: such a warn under a branch (``if``, a loop,
  ``except``, ``match``). It does NOT say the symbol is deprecated: Scrapy's
  ``iterate_spider_output`` deprecates one kind of input, not the function.

A category counts when its name ends in ``DeprecationWarning`` or its class
statically subclasses (Pending)DeprecationWarning (Django's
``RemovedInDjango60Warning``). ``FutureWarning``, a missing category and a
category pyeye can't resolve don't count.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect
from tests.conformance.response_linter import ConformanceViolation, lint_response

_OLD = """\
import warnings
from warnings import warn as _w
from contextlib import nullcontext

from typing_extensions import deprecated
from typing_extensions import deprecated as gone_soon

from .cats import RemovedInBar, RemovedInFoo, RemovedInNext


def gone():
    warnings.warn("gone() is deprecated", DeprecationWarning, stacklevel=2)
    return 1


@deprecated("use new()")
def decorated():
    return 1


@gone_soon("use new()")
def decorated_alias():
    return 1


def branchy(x=None):
    if x is not None:
        warnings.warn("passing x is deprecated", DeprecationWarning)
    return x


def pending():
    _w("pending", category=PendingDeprecationWarning)


def subclass_category():
    warnings.warn("removed in Foo", RemovedInFoo)


def chained_category():
    warnings.warn("removed in Bar", RemovedInBar)


def aliased_category():
    warnings.warn("removed next", RemovedInNext)


def user_warning():
    warnings.warn("careful", UserWarning)


def future_warning():
    warnings.warn("will change", FutureWarning)


def no_category():
    warnings.warn("careful")


def unresolved_category():
    warnings.warn("hmm", some_module.Thing)


@deprecated("use new()")
def both(x=None):
    for item in x or ():
        warnings.warn("iterating is deprecated", DeprecationWarning)
    return x


def nested_scopes():
    def inner():
        warnings.warn("inner is deprecated", DeprecationWarning)

    class Inner:
        def method(self):
            warnings.warn("Inner is deprecated", DeprecationWarning)

    return inner, Inner


def in_with_and_try():
    with nullcontext():
        warnings.warn("always", DeprecationWarning)
    try:
        pass
    except ValueError:
        warnings.warn("only on error", DeprecationWarning)


def plain():
    return 1


class OldClass:
    def __init__(self):
        warnings.warn("OldClass is deprecated", DeprecationWarning)


class ConditionalInit:
    def __init__(self, a=None):
        if a is not None:
            warnings.warn("passing a is deprecated", DeprecationWarning)


@deprecated("use NewClass")
class DecoratedClass:
    pass


class PlainClass:
    x = 1


class WithMethod:
    def method(self):
        warnings.warn("method() is deprecated", DeprecationWarning)


CONSTANT = 1
"""

_CATS = """\
class RemovedInFoo(PendingDeprecationWarning):
    pass


class RemovedInBar(RemovedInFoo):
    pass


RemovedInNext = RemovedInBar  # Django's RemovedInNextVersionWarning shape
"""


def _line(name: str) -> int:
    """The 1-indexed line of the first line in :data:`_OLD` containing *name*."""
    return next(i for i, text in enumerate(_OLD.splitlines(), 1) if name in text)


@pytest.fixture
def analyzer(tmp_path: Path) -> JediAnalyzer:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "old.py").write_text(_OLD, encoding="utf-8")
    (pkg / "cats.py").write_text(_CATS, encoding="utf-8")
    return JediAnalyzer(str(tmp_path))


async def _evidence(analyzer: JediAnalyzer, handle: str) -> Any:
    node = await inspect(handle, analyzer)
    assert node["found"] is True, node
    lint_response(node, "inspect")
    return node.get("deprecation", "<absent>")


def _unconditional(via: str, line: int) -> dict[str, Any]:
    return {"kind": "unconditional", "via": via, "line": line}


def _conditional(line: int) -> dict[str, Any]:
    return {"kind": "conditional", "via": "warn", "line": line}


class TestUnconditional:
    @pytest.mark.asyncio
    async def test_a_top_level_warn(self, analyzer: JediAnalyzer) -> None:
        assert await _evidence(analyzer, "pkg.old.gone") == [
            _unconditional("warn", _line('"gone() is deprecated"'))
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("handle", ["pkg.old.decorated", "pkg.old.decorated_alias"])
    async def test_a_deprecated_decorator(self, analyzer: JediAnalyzer, handle: str) -> None:
        (entry,) = await _evidence(analyzer, handle)
        assert entry["kind"] == "unconditional" and entry["via"] == "decorator"

    @pytest.mark.asyncio
    async def test_a_warn_function_imported_under_another_name(
        self, analyzer: JediAnalyzer
    ) -> None:
        """``from warnings import warn as _w``, and the category as a keyword."""
        assert await _evidence(analyzer, "pkg.old.pending") == [
            _unconditional("warn", _line('_w("pending"'))
        ]

    @pytest.mark.asyncio
    async def test_a_class_whose_init_warns(self, analyzer: JediAnalyzer) -> None:
        assert await _evidence(analyzer, "pkg.old.OldClass") == [
            _unconditional("warn", _line('"OldClass is deprecated"'))
        ]

    @pytest.mark.asyncio
    async def test_a_decorated_class(self, analyzer: JediAnalyzer) -> None:
        (entry,) = await _evidence(analyzer, "pkg.old.DecoratedClass")
        assert entry["via"] == "decorator" and entry["kind"] == "unconditional"

    @pytest.mark.asyncio
    async def test_a_method(self, analyzer: JediAnalyzer) -> None:
        assert await _evidence(analyzer, "pkg.old.WithMethod.method") == [
            _unconditional("warn", _line('"method() is deprecated"'))
        ]

    @pytest.mark.asyncio
    async def test_a_with_block_runs_on_every_call(self, analyzer: JediAnalyzer) -> None:
        """``with`` isn't a branch; ``except`` is."""
        assert await _evidence(analyzer, "pkg.old.in_with_and_try") == [
            _unconditional("warn", _line('"always"')),
            _conditional(_line('"only on error"')),
        ]


class TestConditional:
    @pytest.mark.asyncio
    async def test_a_warn_under_an_if_is_conditional(self, analyzer: JediAnalyzer) -> None:
        """The Scrapy case: it deprecates an input, so the symbol isn't called deprecated."""
        assert await _evidence(analyzer, "pkg.old.branchy") == [
            _conditional(_line('"passing x is deprecated"'))
        ]

    @pytest.mark.asyncio
    async def test_a_class_whose_init_warns_in_a_branch(self, analyzer: JediAnalyzer) -> None:
        assert await _evidence(analyzer, "pkg.old.ConditionalInit") == [
            _conditional(_line('"passing a is deprecated"'))
        ]

    @pytest.mark.asyncio
    async def test_every_piece_of_evidence_is_kept_in_line_order(
        self, analyzer: JediAnalyzer
    ) -> None:
        evidence = await _evidence(analyzer, "pkg.old.both")
        assert [(e["kind"], e["via"]) for e in evidence] == [
            ("unconditional", "decorator"),
            ("conditional", "warn"),
        ]
        assert evidence[1]["line"] == _line('"iterating is deprecated"')


class TestCategories:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "handle",
        ["pkg.old.subclass_category", "pkg.old.chained_category", "pkg.old.aliased_category"],
    )
    async def test_a_category_that_subclasses_a_deprecation_warning(
        self, analyzer: JediAnalyzer, handle: str
    ) -> None:
        """Django's ``RemovedInDjango70Warning`` shape: directly, through a chain, and
        through a module-level alias (``RemovedInNextVersionWarning = RemovedInDjango70Warning``).
        """
        (entry,) = await _evidence(analyzer, handle)
        assert entry == {"kind": "unconditional", "via": "warn", "line": entry["line"]}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "handle",
        [
            "pkg.old.user_warning",
            "pkg.old.future_warning",  # excluded on purpose: also used for behaviour changes
            "pkg.old.no_category",  # UserWarning by default
            "pkg.old.unresolved_category",  # can't resolve: not counted
        ],
    )
    async def test_other_categories_are_not_evidence(
        self, analyzer: JediAnalyzer, handle: str
    ) -> None:
        assert await _evidence(analyzer, handle) == []


class TestMeasuredAndEmptyVsAbsent:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "handle", ["pkg.old.plain", "pkg.old.PlainClass", "pkg.old.nested_scopes"]
    )
    async def test_checked_and_nothing_found_is_an_empty_list(
        self, analyzer: JediAnalyzer, handle: str
    ) -> None:
        """``nested_scopes``: a nested def's or class's warn is that definition's, not this one's."""
        assert await _evidence(analyzer, handle) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("handle", ["pkg.old", "pkg.old.CONSTANT"])
    async def test_kinds_it_does_not_apply_to_have_no_field(
        self, analyzer: JediAnalyzer, handle: str
    ) -> None:
        assert await _evidence(analyzer, handle) == "<absent>"


class TestTheLinterRule:
    """B.6: when present, a list of well-formed entries, and only on functions and classes."""

    @staticmethod
    def _node(**extra: Any) -> dict[str, Any]:
        node: dict[str, Any] = {
            "found": True,
            "handle": "pkg.mod.f",
            "kind": "function",
            "scope": "project",
            "location": {"file": "/x/pkg/mod.py", "line_start": 1, "line_end": 2},
            "docstring": None,
            "signature": "f()",
            "parameters": [],
            "is_async": False,
            "edge_counts": {},
        }
        node.update(extra)
        return node

    @pytest.mark.parametrize(
        "value",
        [
            [],
            [{"kind": "unconditional", "via": "decorator", "line": 3}],
            [{"kind": "conditional", "via": "warn", "line": 9}],
        ],
    )
    def test_well_formed_values_pass(self, value: Any) -> None:
        lint_response(self._node(deprecation=value), "inspect")

    @pytest.mark.parametrize(
        "value",
        [
            None,
            {"kind": "unconditional"},
            [{"kind": "deprecated", "via": "warn", "line": 3}],
            [{"kind": "conditional", "via": "comment", "line": 3}],
            [{"kind": "conditional", "via": "warn", "line": 0}],
            [{"kind": "conditional", "via": "warn"}],
            [{"kind": "conditional", "via": "warn", "line": 3, "extra": 1}],
        ],
    )
    def test_malformed_values_are_rejected(self, value: Any) -> None:
        with pytest.raises(ConformanceViolation, match=r"B\.6"):
            lint_response(self._node(deprecation=value), "inspect")

    def test_it_is_rejected_on_a_kind_it_does_not_apply_to(self) -> None:
        node = self._node(kind="module", deprecation=[])
        with pytest.raises(ConformanceViolation, match=r"B\.6"):
            lint_response(node, "inspect")
