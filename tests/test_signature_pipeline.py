"""``_build_signature`` is an ordered pipeline of named steps (#1167).

Each signature fix (#1106, #999, #1126, #1129, #1159, #407, #437, #1125, #1128)
added a branch to one function. They are now steps in ``_SIGNATURE_STEPS``,
declared once, in the order the #1125 decision entry and its amendments record.
The behaviour is pinned by the existing signature tests
(``test_forwarding_signatures``, ``test_classmethod_signature``,
``test_namedtuple_signatures``, ``test_typeddict_signatures``,
``test_multiline_signatures`` and the inspect/outline/stub suites), unchanged.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

inspect_module = importlib.import_module("pyeye.mcp.operations.inspect")

#: The recorded order: #1106/#1128's no-signature branch, #999's filter with
#: #1126's None drop, #1126's NamedTuple and #1129's TypedDict constructors,
#: #1159's one-line rendering, #407's empty check, #437's wrapper check, and
#: #1125's declared-names and duplicate-name rules.
_ORDER = [
    "_own_def_when_jedi_has_none",
    "_drop_unshowable",
    "_namedtuple_constructor",
    "_typeddict_constructor",
    "_nothing_left",
    "_render_on_one_line",
    "_empty_rendering",
    "_wrapper_rendering",
    "_forwarded_rendering",
    "_duplicate_names",
]


def test_the_steps_are_declared_once_in_the_recorded_order() -> None:
    assert [step.__name__ for step in inspect_module._SIGNATURE_STEPS] == _ORDER


def test_every_step_names_the_issue_it_serves() -> None:
    for step in inspect_module._SIGNATURE_STEPS:
        if step.__name__ == "_nothing_left":
            continue  # bookkeeping: no issue of its own
        assert step.__doc__ is not None and "#" in step.__doc__, step.__name__


def test_the_first_step_that_decides_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """A step returning ``None`` ends the pipeline: later steps never run."""
    seen: list[str] = []

    def deciding(_case: object) -> None:
        seen.append("deciding")
        return None

    def later(_case: object) -> str:
        seen.append("later")
        return "later()"

    monkeypatch.setattr(inspect_module, "_SIGNATURE_STEPS", (deciding, later))
    name = SimpleNamespace(name="f", get_signatures=lambda: [])

    assert inspect_module._build_signature(name) is None
    assert seen == ["deciding"]


def test_when_every_step_passes_jedis_rendering_is_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def render(case: object) -> object:
        case.rendering = "f(a)"  # type: ignore[attr-defined]
        return inspect_module._NEXT

    monkeypatch.setattr(inspect_module, "_SIGNATURE_STEPS", (render,))

    assert inspect_module._build_signature(SimpleNamespace(get_signatures=lambda: [])) == "f(a)"


def test_an_error_in_any_step_means_no_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_case: object) -> object:
        raise RuntimeError("step broke")

    monkeypatch.setattr(inspect_module, "_SIGNATURE_STEPS", (broken,))

    assert inspect_module._build_signature(SimpleNamespace(get_signatures=lambda: [])) is None
