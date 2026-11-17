"""The marker-block binding (#824): parse, render, and every malformed case."""

from __future__ import annotations

import pytest

from pyeye.docs_facts.binding import parse, render
from pyeye.docs_facts.facts import Fact, View, code_list, index, literal, snapshot, table, text

FACTS = index(
    [
        Fact("ci.coverage_threshold", 85, "85%"),
        Fact("edge.members", {"status": "implemented"}, "`members`"),
        Fact("edge.callees", {"status": "implemented"}, "`callees`"),
        View("edges.implemented", ("edge.members", "edge.callees"), "`members`, `callees`"),
        View("edges.table", ("edge.members",), "| Edge |\n|---|\n| `members` |"),
    ]
)


class TestRender:
    def test_block_content_is_rewritten(self) -> None:
        page = "Intro\n<!-- fact:begin edges.table -->\nstale\n<!-- fact:end -->\nAfter\n"

        new, blocks, problems = render(page, FACTS)

        assert problems == []
        assert [b.fact_id for b in blocks] == ["edges.table"]
        assert new == (
            "Intro\n<!-- fact:begin edges.table -->\n| Edge |\n|---|\n| `members` |\n"
            "<!-- fact:end -->\nAfter\n"
        )

    def test_inline_content_is_rewritten(self) -> None:
        page = "Keep it above <!-- fact:begin ci.coverage_threshold -->80%<!-- fact:end -->.\n"

        new, _, problems = render(page, FACTS)

        assert problems == []
        assert (
            new == "Keep it above <!-- fact:begin ci.coverage_threshold -->85%<!-- fact:end -->.\n"
        )

    def test_render_is_idempotent(self) -> None:
        page = "<!-- fact:begin edges.implemented -->\nold\n<!-- fact:end -->\n"
        once, _, _ = render(page, FACTS)
        twice, _, _ = render(once, FACTS)

        assert once == twice

    def test_an_empty_block_is_filled(self) -> None:
        page = "<!-- fact:begin edges.implemented -->\n<!-- fact:end -->\n"

        new, _, problems = render(page, FACTS)

        assert problems == []
        assert "`members`, `callees`" in new

    def test_indented_block_keeps_its_indent(self) -> None:
        page = "- item\n\n  <!-- fact:begin edges.table -->\n  <!-- fact:end -->\n"

        new, _, problems = render(page, FACTS)

        assert problems == []
        assert "  | Edge |\n  |---|\n  | `members` |\n  <!-- fact:end -->" in new

    def test_unknown_id_is_reported_and_left_alone(self) -> None:
        page = "<!-- fact:begin tool.find_references -->\nx\n<!-- fact:end -->\n"

        new, _, problems = render(page, FACTS)

        assert new == page
        assert [(p.line, p.message) for p in problems] == [
            (1, "unknown fact ID 'tool.find_references'")
        ]

    def test_multiline_fact_in_an_inline_block_is_reported(self) -> None:
        page = "See <!-- fact:begin edges.table -->x<!-- fact:end -->.\n"

        new, _, problems = render(page, FACTS)

        assert new == page
        assert "renders on several lines" in problems[0].message

    def test_markers_in_code_are_text(self) -> None:
        page = (
            "Write `<!-- fact:begin nope.id -->` inline.\n"
            "```markdown\n<!-- fact:begin nope.id -->\n<!-- fact:end -->\n```\n"
        )

        new, blocks, problems = render(page, FACTS)

        assert (new, blocks, problems) == (page, [], [])

    def test_text_after_a_block_ends_up_after_it(self) -> None:
        page = (
            "<!-- fact:begin edges.implemented -->\na\n<!-- fact:end -->\n"
            "mid <!-- fact:begin ci.coverage_threshold -->1<!-- fact:end --> end\n"
        )

        new, blocks, problems = render(page, FACTS)

        assert problems == []
        assert len(blocks) == 2
        assert new.endswith(
            "mid <!-- fact:begin ci.coverage_threshold -->85%<!-- fact:end --> end\n"
        )


class TestMalformed:
    @pytest.mark.parametrize(
        ("page", "line", "message"),
        [
            ("<!-- fact:begin a.b -->\nx\n", 1, "fact:begin without a fact:end"),
            ("x\n<!-- fact:end -->\n", 2, "fact:end without a fact:begin"),
            (
                "<!-- fact:begin a.b -->\n<!-- fact:begin c.d -->\n<!-- fact:end -->\n",
                2,
                "fact:begin inside the block opened on line 1",
            ),
            (
                "See <!-- fact:begin a.b -->x\n<!-- fact:end -->\n",
                1,
                "an inline fact block must end on its own line",
            ),
            (
                "<!-- fact:begin a.b -->\nx <!-- fact:end -->\n",
                2,
                "fact:end of a block must start its line",
            ),
        ],
    )
    def test_reported(self, page: str, line: int, message: str) -> None:
        _, problems = parse(page)

        assert [(p.line, p.message) for p in problems] == [(line, message)]


STALE_BLOCK = "<!-- fact:begin ci.coverage_threshold -->70%<!-- fact:end -->\n"


class TestCodeDetection:
    """Review of #834: code detection must never silently switch checking off."""

    @pytest.mark.parametrize(
        "above",
        [
            # A tilde fence holding a backtick line: only ~~~ closes it.
            "~~~\n```\n~~~\n",
            # A 4-backtick fence holding a 3-backtick line: only 4+ closes it.
            "````markdown\n```\nshown\n```\n````\n",
            # A line starting with inline code is not a fence opener.
            "```x``` is inline code\n",
            # An info string after the closer makes it not a closer, but the
            # following plain closer still closes.
            "```\n``` not a closer\n```\n",
            # One stray backtick doesn't make the rest of the line code.
            "a stray ` backtick\n",
        ],
    )
    def test_a_block_after_code_is_still_checked(self, above: str) -> None:
        page = above + STALE_BLOCK

        new, blocks, problems = render(page, FACTS)

        assert problems == []
        assert [b.fact_id for b in blocks] == ["ci.coverage_threshold"]
        assert new.endswith("-->85%<!-- fact:end -->\n")

    def test_a_stray_backtick_on_the_same_line_does_not_hide_the_marker(self) -> None:
        page = "it`s " + STALE_BLOCK

        _, blocks, problems = render(page, FACTS)

        assert problems == []
        assert len(blocks) == 1

    def test_markers_in_a_double_backtick_span_are_text(self) -> None:
        page = "Write ``<!-- fact:begin a.b --> ` <!-- fact:end -->`` here.\n"

        assert parse(page) == ([], [])

    def test_an_unclosed_fence_is_a_problem(self) -> None:
        page = "intro\n```python\n" + STALE_BLOCK

        _, blocks, problems = render(page, FACTS)

        assert blocks == []
        assert [(p.line, p.message.split(":")[0]) for p in problems] == [(2, "unclosed code fence")]

    @pytest.mark.parametrize(
        "marker",
        [
            "<!-- fact:begin x.y-->",
            "<!--fact:begin x.y -->",
            "<!-- fact:end-->",
            "<!-- FACT:END -->",
            "<!-- fact: begin x.y -->",
        ],
    )
    def test_a_near_miss_marker_is_a_problem(self, marker: str) -> None:
        _, problems = parse(f"text {marker} more\n")

        assert [p.message.split(":")[0] for p in problems] == ["malformed fact marker"]

    def test_a_near_miss_in_code_is_text(self) -> None:
        assert parse("`<!-- fact:begin x.y-->`\n") == ([], [])


class TestFacts:
    def test_duplicate_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="produced twice"):
            index([Fact("a.b", 1, "1"), Fact("a.b", 2, "2")])

    @pytest.mark.parametrize("bad", ["nodots", "Upper.case", "a..b", "a.b c"])
    def test_malformed_id_is_rejected(self, bad: str) -> None:
        with pytest.raises(ValueError, match="malformed"):
            index([Fact(bad, 1, "1")])

    def test_snapshot_has_item_facts_only(self) -> None:
        assert snapshot(FACTS) == {
            "ci.coverage_threshold": 85,
            "edge.callees": {"status": "implemented"},
            "edge.members": {"status": "implemented"},
        }

    def test_renderers(self) -> None:
        assert code_list(["a", "b"]) == "`a`, `b`"
        assert [literal(v) for v in (None, True, False, ".", 3)] == [
            "unset",
            "true",
            "false",
            '"."',
            "3",
        ]
        assert table(["A"], [["x|y"]]) == "| A |\n|---|\n| x\\|y |"
        assert text("__path__ * \\") == "\\_\\_path\\_\\_ \\* \\\\"
