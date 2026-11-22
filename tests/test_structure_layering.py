"""``CHECK no-import`` lines against pyeye's ``imports``; type-only imports ignored (#1092)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.docs_facts.structure import dump, layering
from tests.utils.structure import write_project


def _module(
    handle: str,
    imports: tuple[str, ...] = (),
    type_only: tuple[str, ...] = (),
    unresolved: tuple[str, ...] = (),
    measured: bool = True,
) -> dump.Module:
    return dump.Module(handle, "", "", 0, (), imports, type_only, unresolved, measured)


def test_checks_are_parsed_with_their_lines() -> None:
    text = "# Map\n\nCHECK no-import: pkg.core -> pkg.cli\nprose\n- CHECK no-import:a->b.c\n"

    assert layering.checks(text) == [
        layering.Check("pkg.core", "pkg.cli", 3),
        layering.Check("a", "b.c", 5),
    ]


@pytest.mark.parametrize(
    ("name", "prefix", "expected"),
    [
        ("pkg.cli", "pkg.cli", True),
        ("pkg.cli.x", "pkg.cli", True),
        ("pkg.client", "pkg.cli", False),
    ],
)
def test_under(name: str, prefix: str, expected: bool) -> None:
    assert layering.under(name, prefix) is expected


def test_a_runtime_import_breaks_the_check() -> None:
    modules = [
        _module("pkg.core", imports=("pkg.cli.main", "os")),
        _module("pkg.core.sub", imports=("pkg.cli",)),
        _module("pkg.other", imports=("pkg.cli",)),
    ]

    result = layering.run(layering.Check("pkg.core", "pkg.cli", 1), modules)

    assert result.violations == (("pkg.core", "pkg.cli.main"), ("pkg.core.sub", "pkg.cli"))
    assert not result.holds
    assert layering.message(result) == (
        "CHECK no-import: pkg.core -> pkg.cli is broken: "
        "pkg.core imports pkg.cli.main, pkg.core.sub imports pkg.cli"
    )


def test_a_type_only_import_is_ignored_and_listed() -> None:
    result = layering.run(
        layering.Check("pkg.core", "pkg.cli", 1), [_module("pkg.core", type_only=("pkg.cli",))]
    )

    assert result.holds and result.ignored == (("pkg.core", "pkg.cli"),)
    assert layering.message(result) is None


def test_an_unresolved_import_still_counts() -> None:
    result = layering.run(
        layering.Check("pkg.core", "vendor", 1), [_module("pkg.core", unresolved=("vendor.x",))]
    )

    assert result.violations == (("pkg.core", "vendor.x"),)


def test_no_module_under_a_is_unverifiable_not_holding() -> None:
    result = layering.run(layering.Check("ghost", "pkg", 1), [_module("pkg.core")])

    assert not result.verifiable and not result.holds
    assert "can't be verified" in (layering.message(result) or "")


def test_unmeasured_imports_dont_hold() -> None:
    result = layering.run(
        layering.Check("pkg", "x", 1), [_module("pkg.a", measured=False, imports=("x",))]
    )

    assert result.unmeasured == ("pkg.a",) and result.violations == ()
    assert not result.holds
    assert "couldn't read the imports of pkg.a" in (layering.message(result) or "")


def test_many_violations_are_summarised() -> None:
    modules = [_module(f"pkg.m{n}", imports=("bad",)) for n in range(5)]

    message = layering.message(layering.run(layering.Check("pkg", "bad", 1), modules))

    assert message is not None and message.endswith("(and 2 more)")


def test_on_the_fixture_project(tmp_path: Path) -> None:
    """``shapes`` imports ``util`` only under TYPE_CHECKING; ``util`` imports ``paths``."""
    project = write_project(tmp_path)
    modules = dump.collect(project, include=("pkg/*",)).modules
    text = "CHECK no-import: pkg.shapes -> pkg.util\nCHECK no-import: pkg.util -> pkg.paths\n"

    shapes, util = (layering.run(c, modules) for c in layering.checks(text))

    assert shapes.holds and shapes.ignored == (("pkg.shapes", "pkg.util"),)
    assert not util.holds and ("pkg.util", "pkg.paths.helper") in util.violations
