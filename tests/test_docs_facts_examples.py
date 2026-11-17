"""The executed-example grammar and the C10 structure match (#828).

Pure parsing and matching; ``tests/test_docs_examples.py`` runs the examples.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.docs_facts import cli, docs
from pyeye.docs_facts.docs import DocEntry
from pyeye.docs_facts.examples import allows_examples, match_shown, parse_examples

F = "```"


def _example(info: str, body: str) -> str:
    return f"{F}{info}\n{body}\n{F}\n"


class TestGrammar:
    def test_an_example_and_its_output(self) -> None:
        page = (
            "Intro.\n\n"
            + _example("json pyeye-example tool=inspect", '{"handle": "a.b"}')
            + "\n"
            + _example("json pyeye-output", '{"found": true}')
        )

        examples, problems = parse_examples(page)

        assert problems == []
        assert [(e.line, e.tool, e.fixture, e.args, e.output) for e in examples] == [
            (3, "inspect", "docs_examples", {"handle": "a.b"}, {"found": True})
        ]

    def test_an_example_without_output_and_a_fixture(self) -> None:
        page = _example("json pyeye-example tool=outline fixture=other", '{"handle": "x"}')

        examples, problems = parse_examples(page)

        assert problems == []
        assert examples[0].fixture == "other"
        assert not examples[0].shows_output

    def test_untagged_fences_are_prose(self) -> None:
        page = _example("json", "{not json") + _example("python", "x = 1")

        assert parse_examples(page) == ([], [])

    @pytest.mark.parametrize(
        ("info", "body", "message"),
        [
            ("json pyeye-exampel tool=inspect", "{}", "malformed example tag"),
            ("pyeye-example tool=inspect", "{}", "malformed example tag"),
            ("json pyeye-example", "{}", "needs tool=<tool>"),
            ("json pyeye-example tool=inspect tool=expand", "{}", "bad example key"),
            ("json pyeye-example tool=inspect colour=red", "{}", "bad example key"),
            ("json pyeye-example tool=", "{}", "bad example key"),
            ("json pyeye-output tool=inspect", "{}", "takes no keys"),
            ("json pyeye-example tool=inspect", "{not json", "body is not JSON"),
            ("json pyeye-example tool=inspect", "[1]", "must be a JSON object"),
            (
                "json pyeye-example tool=inspect",
                '{"project_path": "."}',
                "don't write project_path",
            ),
        ],
    )
    def test_malformed_tags_and_bodies(self, info: str, body: str, message: str) -> None:
        examples, problems = parse_examples(_example(info, body))

        assert examples == []
        assert len(problems) == 1 and message in problems[0].message

    @pytest.mark.parametrize(
        "page",
        [
            # No example before it.
            _example("json pyeye-output", "{}"),
            # Prose between the example and its output.
            _example("json pyeye-example tool=inspect", "{}")
            + "Some prose.\n"
            + _example("json pyeye-output", "{}"),
            # Another fence in between.
            _example("json pyeye-example tool=inspect", "{}")
            + _example("python", "x")
            + _example("json pyeye-output", "{}"),
        ],
    )
    def test_an_output_must_directly_follow_an_example(self, page: str) -> None:
        _, problems = parse_examples(page)

        assert [p.message for p in problems] == ["a `pyeye-output` block must follow an example"]

    def test_only_one_output_per_example(self) -> None:
        page = (
            _example("json pyeye-example tool=inspect", "{}")
            + _example("json pyeye-output", "{}")
            + _example("json pyeye-output", "{}")
        )

        examples, problems = parse_examples(page)

        assert len(examples) == 1 and examples[0].output == {}
        assert [p.message for p in problems] == ["an example can show only one output"]

    def test_examples_inside_another_fence_are_text(self) -> None:
        page = "````markdown\n" + _example("json pyeye-example tool=nope", "{}") + "````\n"

        assert parse_examples(page) == ([], [])


class TestWhereExamplesLive:
    @pytest.mark.parametrize(
        ("entry", "allowed"),
        [
            (DocEntry("docs/api/flask-tools.md", "human", "prose"), True),
            (DocEntry("docs/reference/tools.md", "both", "reference"), True),
            (DocEntry("skills/python-explore/SKILL.md", "claude", "skill"), True),
            (DocEntry("README.md", "human", "prose"), False),
        ],
    )
    def test_allows_examples(self, entry: DocEntry, allowed: bool) -> None:
        assert allows_examples(entry) is allowed

    def test_check_reports_a_bad_tag_and_a_misplaced_example(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "docs" / "api").mkdir(parents=True)
        (tmp_path / "docs" / "api" / "a.md").write_text(
            _example("json pyeye-example", "{}"), encoding="utf-8"
        )
        (tmp_path / "README.md").write_text(
            "x\n" + _example("json pyeye-example tool=inspect", "{}"), encoding="utf-8"
        )
        monkeypatch.setattr(
            docs,
            "DOCS",
            (
                DocEntry("README.md", "human", "prose"),
                DocEntry("docs/api/a.md", "human", "prose"),
            ),
        )
        monkeypatch.setattr(docs, "REFERENCE_PAGES", ())
        monkeypatch.setattr(cli.pages, "PAGES", {})

        result = cli.plan(tmp_path, facts={})

        assert result.problems == [
            "README.md:2: runnable examples belong in docs/api/, docs/reference/ or a skill",
            "docs/api/a.md:1: `pyeye-example` needs tool=<tool>: 'json pyeye-example'",
        ]


REAL = {
    "found": True,
    "kind": "class",
    "handle": "a.B",
    "location": {"file": "/x/a.py", "line_start": 1},
    "edge_counts": {"members": 3},
    "stubs": [{"handle": "a.c"}, {"handle": "a.d"}],
}


class TestMatchShown:
    """C10, rule by rule: each passing form, then each failing one."""

    @pytest.mark.parametrize(
        "shown",
        [
            # Every key, values differing (only discriminators are compared).
            {
                "found": True,
                "kind": "class",
                "handle": "other",
                "location": {"file": "f", "line_start": 9},
                "edge_counts": {"members": 0},
                "stubs": [{"handle": "x"}, {"handle": "y"}],
            },
            # Trimmed levels, marked.
            {"found": True, "location": {"…": "<omitted>"}, "…": "<omitted>"},
            # A trimmed array, marked.
            {"found": True, "stubs": [{"handle": "a.c"}, "<omitted>"], "…": "<omitted>"},
            # An asserted absence that holds.
            {"found": True, "edge_counts": {"members": 3, "callers": "<absent>"}, "…": "<omitted>"},
        ],
    )
    def test_matches(self, shown: object) -> None:
        assert match_shown(shown, REAL) == []

    @pytest.mark.parametrize(
        ("shown", "message"),
        [
            ({"found": False, "…": "<omitted>"}, "$.found: shown as False"),
            ({"kind": "function", "…": "<omitted>"}, "$.kind: shown as 'function'"),
            ({"found": True, "extra": 1, "…": "<omitted>"}, "$.extra: shown, but not in"),
            ({"handle": 1, "…": "<omitted>"}, "$.handle: shown as number"),
            ({"location": [], "…": "<omitted>"}, "$.location: shown as an array"),
            ({"stubs": {}, "…": "<omitted>"}, "$.stubs: shown as an object"),
            ({"found": True}, "leaves out ['edge_counts', 'handle', 'kind', 'location', 'stubs']"),
            ({**REAL, "…": "<omitted>"}, "nothing is left out"),
            ({"found": True, "…": "trimmed"}, '"…" must be "<omitted>"'),
            ({"handle": "<absent>", "…": "<omitted>"}, "$.handle: shown as <absent>, but"),
            (
                {"stubs": [{"handle": "a.c"}], "…": "<omitted>"},
                "shows 1 of 2 items without a final",
            ),
            (
                {"stubs": [{"handle": "a"}, {"handle": "b"}, "<omitted>"], "…": "<omitted>"},
                'ends with "<omitted>", but every item is shown',
            ),
            (
                {"stubs": [{"handle": "a"}, {"handle": "b"}, {"handle": "c"}], "…": "<omitted>"},
                "shows 3 items, but the response has 2",
            ),
        ],
    )
    def test_mismatches(self, shown: object, message: str) -> None:
        mismatches = match_shown(shown, REAL)

        assert any(message in m for m in mismatches), mismatches

    def test_null_is_its_own_kind(self) -> None:
        assert match_shown({"a": None}, {"a": None}) == []
        assert match_shown({"a": None}, {"a": 0}) == [
            "$.a: shown as null, but the response has number"
        ]

    def test_top_level_array(self) -> None:
        assert match_shown([{"a": 1}, "<omitted>"], [{"a": 2}, {"a": 3}]) == []
        assert match_shown({"a": 1}, [{"a": 1}]) == [
            "$: shown as an object, but the response has array"
        ]
