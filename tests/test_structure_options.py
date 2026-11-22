"""The ``structure`` kind's options: validated as data, refused by name (#1092)."""

from __future__ import annotations

from typing import Any

import pytest

from pyeye.docs_facts.structure import options


def test_defaults() -> None:
    assert options.parse({}) == options.Options(
        prefix="arch", include=("*",), exclude=(), strict_source=False, within_areas=False
    )


def test_every_option() -> None:
    parsed = options.parse(
        {
            "prefix": "arch2",
            "include": ["src/*"],
            "exclude": ["*/tests/*"],
            "strict_source": True,
            "within_areas": True,
        }
    )

    assert parsed == options.Options("arch2", ("src/*",), ("*/tests/*",), True, True)


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ({"areas": {}}, "unknown option(s) 'areas'"),
        ({"prefix": "Arch"}, "'prefix' must be"),
        ({"prefix": "arch.x"}, "'prefix' must be"),
        ({"prefix": 3}, "'prefix' must be"),
        ({"include": "src/*"}, "'include' must be a list"),
        ({"include": [""]}, "'include' must be a list"),
        ({"include": []}, "'include' is empty"),
        ({"exclude": [1]}, "'exclude' must be a list"),
        ({"strict_source": "yes"}, "'strict_source' must be true or false"),
        ({"within_areas": 1}, "'within_areas' must be true or false"),
    ],
)
def test_bad_options_are_refused_by_name(table: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message.replace("(", r"\(").replace(")", r"\)")):
        options.parse(table)
