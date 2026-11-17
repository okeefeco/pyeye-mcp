"""The prose rules over the doc registry (#825, design #818 §1).

Replaces three point checks that each kept a private file list:
``test_static_surface_ceiling_docs`` (#417), ``test_absence_prose_conformance``
(#568) and ``test_edge_counts_prose_conformance`` (#396). The scanners keep their
teeth: each phrasing that once passed CI while wrong is still flagged here, and
each honest phrasing still passes. What they scan now comes from the registry
and the live tool descriptions, so a new page or tool is covered on the day it
lands.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import MappingProxyType

import pytest

from pyeye.docs_facts import registry, rules
from pyeye.docs_facts.docs import DOCS, DocEntry
from pyeye.docs_facts.extractors.edges import inspect_unmeasured
from pyeye.docs_facts.facts import Fact
from pyeye.mcp.operations.edges import resolve_members, resolve_subclasses
from pyeye.mcp.operations.outline import outline as outline_operation
from tests.conformance.response_linter import _PHASE4_UNMEASURED_EDGES

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def facts() -> dict:
    return registry.build(ROOT)


def _page(text: str, kind: str | None = "prose") -> rules.Page:
    return rules.Page("p.md", text, rules.prose_text(text), kind)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# #568: absence is unknown, not nonexistence
# ---------------------------------------------------------------------------

# Verbatim from main before #568: each passed CI while contradicting the invariant.
PRE_568_MISSES = {
    "skill not-found bullet": (
        '    `reason: "unresolved"`. That means "this handle doesn\'t exist as written" (often the\n'
        "    right name under the wrong module path), not an empty symbol.\n"
    ),
    "skill static-surface ceiling (scope)": (
        "**Static-surface ceiling.** These structural edges are complete over what is\n"
        "*written in source*, not over what exists at runtime.\n"
    ),
    "skill static-surface ceiling (absence)": (
        'An absent member or subclass means "not in\nsource," **not** "not at runtime"\n'
    ),
    "outline docstring": (
        '    ``DoesNotExist``.  An absent member is "not in source," not "not at runtime."\n'
    ),
}

HONEST_ABSENCE_PROSE = {
    "unresolved is unknown": (
        "That means pyeye couldn't resolve this handle as written: unknown, not evidence "
        "the symbol is absent."
    ),
    "filesystem fact": (
        "The call errors only for invalid arguments or a ``project_path`` that doesn't exist."
    ),
    "missing file": "Raises FileNotFoundError: If file doesn't exist.",
    # Filesystem wording in pyeye.mcp code comments, which get no allowance.
    "comment: create the file": "# if the file does not exist, create it",
    "comment: path": "path does not exist",
    "comment: directory": "the cache directory doesn't exist yet",
    "comment: named file": "the config file named x does not exist",
    "measured scope": (
        "An absent member is unknown outside the measured scope, not absent from the code."
    ),
}


class TestAbsenceRule:
    @pytest.mark.parametrize("name", sorted(PRE_568_MISSES))
    def test_flags_each_pre_568_phrasing(self, name: str) -> None:
        assert rules.absence_claims(PRE_568_MISSES[name]), name

    @pytest.mark.parametrize("name", sorted(HONEST_ABSENCE_PROSE))
    def test_allows_honest_prose(self, name: str) -> None:
        assert rules.absence_claims(HONEST_ABSENCE_PROSE[name]) == []

    def test_reports_the_paragraph_line(self) -> None:
        text = "Intro.\n\nSecond\nparagraph: the symbol doesn't exist.\n"

        assert [f.line for f in rules.absence_claims(text)] == [3]

    def test_operation_docstrings_are_honest(self) -> None:
        """Internal contracts, not docs, checked by object rather than by file."""
        for obj in (resolve_members, resolve_subclasses, outline_operation):
            assert rules.absence_claims(obj.__doc__ or "") == [], obj.__name__

    def test_invariant_stated_as_general_rule(self) -> None:
        """The general rule is stated in the design doc and in the skill."""
        rule = "is unknown, not absent"
        for surface in ("docs/api-redesign.md", "skills/python-explore/SKILL.md"):
            flat = " ".join((ROOT / surface).read_text(encoding="utf-8").split())
            assert rule in flat.replace("*", ""), surface


# ---------------------------------------------------------------------------
# #396: no unmeasured edge inside edge_counts
# ---------------------------------------------------------------------------

# Verbatim from the pre-#395 tree: each passed CI while contradicting the measured set.
PRE_395_MISSES = {
    "skill example block": (
        'inspect("myapp.config.Settings")   -> kind, signature, docstring,\n'
        "                                        edge_counts: { members: 7, superclasses: 1, "
        "subclasses: 0 }\n"
    ),
    "skill absence-vs-zero paragraph": (
        'When you read `edge_counts`, a **missing key means "not measured," not "zero."** A\n'
        "present `subclasses: 0` means measured-and-none (genuinely unextended). An *absent*\n"
        "`callers` key means pyeye didn't measure it — don't read that as \"no callers.\"\n"
    ),
    "server.py wrapped RST docstring": (
        "        (direct + indirect), so ``len(stubs) == inspect(handle).edge_counts``\n"
        "        ``.subclasses``.  ``stubs: []`` means the class has no project\n"
    ),
    "server.py comment": (
        "# DEPRECATED: replaced by inspect(handle).edge_counts.subclasses for the count; "
        'future expand(handle, edge="subclasses") for the list.\n'
    ),
}

CORRECT_OMISSION_PROSE = {
    "omits callers and references": (
        "Likewise, `inspect`'s `edge_counts` simply **omits** `callers`\n"
        "and `references` — it does not report them as `0`.\n"
    ),
    "absent key is not zero": (
        'When you read `edge_counts`, a **missing key means "not measured," not "zero."** A\n'
        "present `superclasses: 0` means measured-and-none (the class has no bases). An *absent*\n"
        "`callers` key means pyeye didn't measure it — don't read that as \"no callers.\"\n"
    ),
    "measured example": "edge_counts: { members: 7, superclasses: 1 }\n",
}


class TestEdgeCountsRule:
    @pytest.mark.parametrize("name", list(PRE_395_MISSES))
    def test_flags_each_pre_395_miss(self, name: str) -> None:
        assert rules.edge_counts_claims(PRE_395_MISSES[name], _PHASE4_UNMEASURED_EDGES), name

    @pytest.mark.parametrize("name", list(CORRECT_OMISSION_PROSE))
    def test_allows_correct_omission_prose(self, name: str) -> None:
        text = CORRECT_OMISSION_PROSE[name]

        assert rules.edge_counts_claims(text, _PHASE4_UNMEASURED_EDGES) == []

    @pytest.mark.parametrize(
        "text",
        ['edge_counts["callers"] is the caller count', 'n = result["edge_counts"]["callers"]'],
    )
    def test_flags_subscript_access(self, text: str) -> None:
        assert rules.edge_counts_claims(text, _PHASE4_UNMEASURED_EDGES)

    def test_unmeasured_set_is_the_linters(self, facts: dict) -> None:
        """The rule and the live-response linter read one set, so they move together."""
        assert set(facts[rules.UNMEASURED_FACT].value) == _PHASE4_UNMEASURED_EDGES
        assert {"subclasses", "callers", "references"} <= _PHASE4_UNMEASURED_EDGES
        assert not {"members", "superclasses"} & _PHASE4_UNMEASURED_EDGES

    def test_reading_the_set_fails_loudly_when_it_moves(self, tmp_path: Path) -> None:
        linter = tmp_path / "tests" / "conformance" / "response_linter.py"
        linter.parent.mkdir(parents=True)
        linter.write_text("_PHASE4_UNMEASURED_EDGES = compute()\n", encoding="utf-8")

        with pytest.raises(ValueError, match="no longer assigns"):
            inspect_unmeasured(tmp_path)


# ---------------------------------------------------------------------------
# #417: the static-surface ceiling caveat
# ---------------------------------------------------------------------------


CEILING_FACTS = {
    "edge.members": Fact("edge.members", {"ceiling": "static_definitions"}, ""),
    "edge.subclasses": Fact("edge.subclasses", {"ceiling": "literal_subclassing"}, ""),
    "edge.callees": Fact("edge.callees", {"ceiling": "static_calls"}, ""),
}


class TestCeilingRule:
    def test_the_static_set_comes_from_the_ceiling_facts(self, facts: dict) -> None:
        """C12: no edge names in rules.py; the edges whose ceiling is static."""
        assert rules.static_edges(CEILING_FACTS) == ("members", "subclasses")
        assert rules.static_edges(facts) == ("members", "subclasses")

    def test_a_new_static_edge_is_covered_without_a_code_change(self) -> None:
        facts = {
            **CEILING_FACTS,
            "edge.attributes": Fact("edge.attributes", {"ceiling": "static_definitions"}, ""),
        }
        text = "  - ``attributes``  — the class's attributes.\n"

        assert rules.missing_ceiling(_page(text, kind=None), facts)

    def test_an_edge_with_another_ceiling_needs_no_marker(self) -> None:
        text = "  - ``callees``  — what it calls.\n"

        assert rules.missing_ceiling(_page(text, kind=None), CEILING_FACTS) == []

    def test_a_page_binding_the_edge_list_needs_the_marker(self) -> None:
        page = _page("Edges:\n<!-- fact:begin edges.implemented -->\nx\n<!-- fact:end -->\n")

        assert [f.line for f in rules.missing_ceiling(page, CEILING_FACTS)] == [2]

    def test_the_marker_satisfies_it(self) -> None:
        page = _page(
            "**Static-surface ceiling.** ...\n"
            "<!-- fact:begin edges.implemented -->\nx\n<!-- fact:end -->\n"
        )

        assert rules.missing_ceiling(page, CEILING_FACTS) == []

    def test_a_description_naming_a_static_edge_needs_the_marker(self) -> None:
        page = _page('Follows "members".', kind=None)

        assert rules.missing_ceiling(page, CEILING_FACTS)

    def test_each_static_edge_entry_needs_its_own_marker(self) -> None:
        """#417: expand's members AND subclasses entries each carry the caveat."""
        text = (
            "Supported edges:\n"
            "  - ``members``  — children. Static-surface ceiling: runtime members.\n"
            "  - ``callees``  — calls.\n"
            "  - ``subclasses``  — direct subclasses only.\n"
        )

        found = rules.missing_ceiling(_page(text, kind=None), CEILING_FACTS)

        assert [(f.line, "subclasses" in f.message) for f in found] == [(4, True)]

    def test_the_live_expand_entries_are_checked_per_edge(self) -> None:
        expand = rules._tool_descriptions()["expand"]
        entries = rules._edge_entries(expand)

        assert {"members", "subclasses"} <= set(entries)
        assert all(rules.CEILING_MARKER in entries[e][1] for e in ("members", "subclasses"))

    def test_a_description_naming_no_static_edge_is_left_alone(self) -> None:
        assert rules.missing_ceiling(_page("Resolves a name.", kind=None), CEILING_FACTS) == []

    def test_operation_docstrings_carry_the_marker(self) -> None:
        """#417 cites these internal contracts; checked by object, not by file."""
        for obj in (resolve_members, resolve_subclasses, outline_operation):
            assert rules.CEILING_MARKER in (obj.__doc__ or ""), obj.__name__

    def test_the_skill_carries_the_marker(self) -> None:
        text = (ROOT / "skills" / "python-explore" / "SKILL.md").read_text(encoding="utf-8")

        assert rules.CEILING_MARKER in text


# ---------------------------------------------------------------------------
# The machinery: fact blocks, the ratchet, the allow-list keys
# ---------------------------------------------------------------------------


class TestProseText:
    def test_fact_block_content_is_blanked_and_lines_kept(self) -> None:
        text = "A\n<!-- fact:begin x.y -->\nthe symbol doesn't exist\n<!-- fact:end -->\nB\n"

        prose = rules.prose_text(text)

        assert "exist" not in prose
        assert prose.count("\n") == text.count("\n")
        assert rules.absence_claims(prose) == []

    def test_inline_blocks_are_blanked_too(self) -> None:
        prose = rules.prose_text("Min <!-- fact:begin ci.x -->85%<!-- fact:end --> total.\n")

        assert "85%" not in prose


def _entry(**allow: tuple[str, ...]) -> DocEntry:
    return DocEntry("p.md", "human", "prose", MappingProxyType(dict(allow)))


A, B = "first finding", "second finding"


class TestRatchet:
    def test_matching_findings_pass(self) -> None:
        assert rules.ratchet(_entry(**{"absence-prose": (A, A)}), "absence-prose", [A, A]) is None
        assert rules.ratchet(_entry(), "absence-prose", []) is None

    def test_a_new_violation_fails(self) -> None:
        problem = rules.ratchet(_entry(), "absence-prose", [A])

        assert problem is not None and "not in the page's allow-list" in problem

    def test_a_fix_must_remove_its_allowance(self) -> None:
        problem = rules.ratchet(_entry(**{"absence-prose": (A, B)}), "absence-prose", [A])

        assert problem is not None and "no longer found" in problem and B in problem

    def test_a_fix_cant_be_traded_for_a_new_violation(self) -> None:
        """Counting lines let one fix pay for one new violation; messages don't."""
        assert rules.ratchet(_entry(**{"absence-prose": (A,)}), "absence-prose", [B])

    def test_an_allowance_covers_only_its_own_finding(self) -> None:
        """More findings on an allowed line are new findings, not covered ones."""
        assert rules.ratchet(_entry(**{"env-name": (A,)}), "env-name", [A, B])

    def test_an_unknown_rule_key_fails(self) -> None:
        problems = rules.allow_problems([_entry(**{"removed-names": (A,)})])

        assert problems and "unknown rule 'removed-names'" in problems[0]

    @pytest.mark.parametrize("value", [(), "a bare string"])
    def test_an_allowance_must_list_messages(self, value: object) -> None:
        assert rules.allow_problems([_entry(**{"absence-prose": value})])  # type: ignore[arg-type]

    def test_the_default_allow_is_immutable(self) -> None:
        entry = DocEntry("p.md", "human", "prose")

        with pytest.raises(TypeError):
            entry.allow["absence-prose"] = (A,)  # type: ignore[index]

    def test_the_registry_allow_lists_are_valid(self) -> None:
        assert rules.allow_problems(DOCS) == []


class TestRun:
    @staticmethod
    def _repo(tmp_path: Path, text: str, kind: str = "prose", **allow: tuple[str, ...]) -> tuple:
        (tmp_path / "p.md").write_text(text, encoding="utf-8")
        entry = DocEntry("p.md", "human", kind, MappingProxyType(dict(allow)))  # type: ignore[arg-type]
        return tmp_path, (entry,)

    FACTS = {rules.UNMEASURED_FACT: Fact(rules.UNMEASURED_FACT, ["callers"], "")}

    def _run(self, root: Path, docs: tuple, **surfaces: object) -> list[str]:
        surfaces.setdefault("descriptions", {})
        surfaces.setdefault("strings", ())
        return rules.run(root, self.FACTS, docs, **surfaces)  # type: ignore[arg-type]

    def test_a_violation_names_page_line_and_rule(self, tmp_path: Path) -> None:
        root, docs = self._repo(tmp_path, "x\n\nThe symbol doesn't exist.\n")

        problems = self._run(root, docs)

        assert "p.md: absence-prose: 1 finding(s) not in the page's allow-list" in problems
        assert any(p.startswith("p.md:3: absence-prose:") for p in problems)

    def test_an_allowed_violation_passes(self, tmp_path: Path) -> None:
        text = "The symbol doesn't exist.\n"
        message = rules.absence_claims(text)[0].message
        root, docs = self._repo(tmp_path, text, **{"absence-prose": (message,)})

        assert self._run(root, docs) == []

    def test_only_the_unallowed_finding_is_reported(self, tmp_path: Path) -> None:
        text = "The symbol doesn't exist.\n\nThe handle does not exist.\n"
        first = rules.absence_claims(text)[0].message
        root, docs = self._repo(tmp_path, text, **{"absence-prose": (first,)})

        problems = self._run(root, docs)

        detail = [p for p in problems if re.match(r"p\.md:\d", p)]
        assert len(detail) == 1 and detail[0].startswith("p.md:3:")

    def test_history_pages_are_exempt_from_the_phrasing_rules(self, tmp_path: Path) -> None:
        root, docs = self._repo(tmp_path, "The symbol doesn't exist.\n", kind="history")

        assert self._run(root, docs) == []

    def test_history_pages_get_the_fact_rules(self, tmp_path: Path) -> None:
        """A migration guide is where people copy env vars and commands from (C11)."""
        text = "Set PYEYE_PACKAGES=../lib, then run `uv run pyeye`.\n"
        root, docs = self._repo(tmp_path, text, kind="history")
        facts = {**self.FACTS, **ENV_FACTS}

        problems = rules.run(root, facts, docs, descriptions={}, strings=())

        assert any("env-name: PYEYE_PACKAGES" in p for p in problems)
        assert any("server-command: no console script 'pyeye'" in p for p in problems)

    def test_released_changelog_sections_are_exempt(self, tmp_path: Path) -> None:
        text = (
            "# Changelog\n\n## [Unreleased]\n\n- Set `PYEYE_DEBUG`.\n\n"
            "## [2.0.0] - 2026-11-07\n\n- Set `PYEYE_TIMEOUT`.\n"
        )
        (tmp_path / "CHANGELOG.md").write_text(text, encoding="utf-8")
        docs = (DocEntry("CHANGELOG.md", "human", "history"),)

        problems = rules.run(
            tmp_path, {**self.FACTS, **ENV_FACTS}, docs, descriptions={}, strings=()
        )

        assert any("CHANGELOG.md:5: env-name: PYEYE_DEBUG" in p for p in problems)
        assert not any("PYEYE_TIMEOUT" in p for p in problems)

    def test_released_blanked_keeps_lines(self) -> None:
        text = "## [Unreleased]\nx\n## [1.0.0] - d\nold\n"

        blanked = rules.released_blanked(text)

        assert blanked.count("\n") == text.count("\n")
        assert "old" not in blanked and "x" in blanked
        assert rules.released_blanked("no headings\n") == "no headings\n"

    def test_tool_descriptions_are_scanned_with_no_allowance(self, tmp_path: Path) -> None:
        root, docs = self._repo(tmp_path, "fine\n")

        problems = self._run(root, docs, descriptions={"t": "Each name that doesn't exist."})

        assert problems and problems[0].startswith("tool:t:1: absence-prose:")

    def test_code_strings_report_the_source_line(self, tmp_path: Path) -> None:
        root, docs = self._repo(tmp_path, "fine\n")
        text = "ok\n\nThe handle does not exist."
        page = rules.Page("pyeye/mcp/x.py", text, text, None, 40)

        problems = self._run(root, docs, strings=[page])

        assert problems and problems[0].startswith("pyeye/mcp/x.py:42: absence-prose:")

    def test_the_repo_passes_every_rule(self, facts: dict) -> None:
        """The live run, as ``docs_facts check`` does it: every surface."""
        assert rules.run(ROOT, facts) == []


class TestCodeStrings:
    """The third surface (design C10, Q8): what the MCP package says to a model."""

    @pytest.fixture(scope="class")
    def strings(self) -> list[rules.Page]:
        return list(rules.code_strings())

    def test_it_covers_the_response_builders(self, strings: list[rules.Page]) -> None:
        modules = {p.name for p in strings}
        for module in ("not_found", "resolve", "inspect", "edges", "outline", "expand"):
            assert f"pyeye/mcp/operations/{module}.py" in modules, module
        assert "pyeye/mcp/server.py" in modules

    def test_it_is_not_vacuous_for_either_rule(self, strings: list[rules.Page]) -> None:
        """The old #396 guard: a scan that never sees edge_counts proves nothing."""
        assert any("edge_counts" in p.text for p in strings if p.name == "pyeye/mcp/server.py")
        assert any("did not resolve" in p.text for p in strings)

    def test_comments_are_a_surface(self, strings: list[rules.Page]) -> None:
        """The original #395 miss was a comment in server.py (C11)."""
        page = rules.Page("pyeye/mcp/x.py", "", "", None)
        source = "x = 1\n# replaced by inspect(h).edge_counts\n# .subclasses for the count\ny = 2\n"

        blocks = list(rules._comment_blocks(source))

        assert blocks == [(2, "replaced by inspect(h).edge_counts\n.subclasses for the count")]
        assert rules.edge_counts_claims(blocks[0][1], ["subclasses"])
        assert page.line == 1
        assert any(p.text and p.name == "pyeye/mcp/server.py" for p in strings)

    def test_separate_comment_runs_are_separate_pages(self) -> None:
        source = "# one\nx = 1\n# two\n"

        assert list(rules._comment_blocks(source)) == [(1, "one"), (3, "two")]

    def test_fstrings_render_with_placeholders(self) -> None:
        tree = ast.parse('x = f"Handle {h!r} does not exist."')
        node = tree.body[0].value  # type: ignore[attr-defined]

        assert rules._rendered(node) == "Handle {} does not exist."
        assert rules.absence_claims(rules._rendered(node) or "")


# ---------------------------------------------------------------------------
# #556 / #628: env vars, and #553: server commands
# ---------------------------------------------------------------------------


def _env(status: str) -> dict:
    return {"type": "int", "status": status}


ENV_FACTS = {
    "env.PYEYE_CACHE_TTL": Fact("env.PYEYE_CACHE_TTL", _env("live"), ""),
    "env.PYEYE_POOL_TTL": Fact("env.PYEYE_POOL_TTL", _env("deprecated"), ""),
    "env.PYEYE_IDLE": Fact("env.PYEYE_IDLE", _env("unused"), ""),
    "cli.script.pyeye-mcp": Fact("cli.script.pyeye-mcp", {}, ""),
}


class TestEnvNameRule:
    @pytest.mark.parametrize(
        "line",
        [
            "Set `PYEYE_CACHE_TTL` to 60.",
            "`PYEYE_POOL_TTL` is deprecated and has no effect.",
        ],
    )
    def test_live_deprecated_and_removed_with_their_word_pass(self, line: str) -> None:
        assert rules.env_name_claims(line, ENV_FACTS) == []

    @pytest.mark.parametrize(
        ("line", "why"),
        [
            ("Set `PYEYE_POOL_TTL` to 5.", "deprecated; say so"),
            ("Tune `PYEYE_IDLE`.", "loaded but nothing uses it"),
            ("Set `PYEYE_PACKAGES=../lib`.", "not a variable pyeye reads"),
            ("Set `PYEYE_NAMESPACE_company`.", "not a variable pyeye reads"),
            ("Use `PYEYE_DEBUG=1`.", "not a variable pyeye reads"),
        ],
    )
    def test_names_that_take_no_effect_fail(self, line: str, why: str) -> None:
        found = rules.env_name_claims(line, ENV_FACTS)

        assert len(found) == 1 and why in found[0].message

    def test_never_read_names_fail_even_beside_removed(self) -> None:
        """They never existed, so "removed" would be a false claim (D12)."""
        assert rules.env_name_claims("`PYEYE_DEBUG` was removed.", ENV_FACTS)

    def test_a_removed_name_passes_only_beside_removed(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """The hook #826 fills from docs/facts/removed.json."""
        monkeypatch.setattr(rules, "_removed_names", lambda: frozenset({"PYEYE_OLD"}))

        assert rules.env_name_claims("`PYEYE_OLD` was removed in 2.0.", ENV_FACTS) == []
        assert rules.env_name_claims("Set `PYEYE_OLD`.", ENV_FACTS)
        assert rules.server_command_claims("`uv run pyeye-old` was removed.", ENV_FACTS)


class TestServerCommandRule:
    @pytest.mark.parametrize(
        "line",
        [
            "Run `uv run pyeye-mcp`.",
            "Or `python -m pyeye.mcp`.",
            "Edit `src/pyeye/mcp/server.py` to add a tool.",
        ],
    )
    def test_working_commands_pass(self, line: str) -> None:
        assert rules.server_command_claims(line, ENV_FACTS) == []

    @pytest.mark.parametrize(
        "line",
        [
            "uv run mcp dev src/pyeye/server.py",
            "uv run python ~/repo/src/pyeye/mcp/server.py",
            "Run `uv run pyeye`.",
            "`uv run pyeye` was removed; the script is `pyeye-mcp`.",
            "claude mcp add /path/to/pyeye",
            'claude mcp add pyeye --command "uv"',
            'claude mcp add pyeye --directory "/path/to/your/repo"',
        ],
    )
    def test_commands_that_never_worked_fail(self, line: str) -> None:
        assert rules.server_command_claims(line, ENV_FACTS)
