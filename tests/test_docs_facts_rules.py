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


class TestCeilingRule:
    def test_a_page_binding_the_edge_list_needs_the_marker(self) -> None:
        page = _page("Edges:\n<!-- fact:begin edges.implemented -->\nx\n<!-- fact:end -->\n")

        assert [f.line for f in rules.missing_ceiling(page, {})] == [2]

    def test_the_marker_satisfies_it(self) -> None:
        page = _page(
            "**Static-surface ceiling.** ...\n"
            "<!-- fact:begin edges.implemented -->\nx\n<!-- fact:end -->\n"
        )

        assert rules.missing_ceiling(page, {}) == []

    def test_a_description_naming_a_static_edge_needs_the_marker(self) -> None:
        page = _page('Follows "members".', kind=None)

        assert rules.missing_ceiling(page, {})

    def test_a_description_naming_no_static_edge_is_left_alone(self) -> None:
        assert rules.missing_ceiling(_page("Resolves a name.", kind=None), {}) == []

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


def _entry(**allow: int) -> DocEntry:
    return DocEntry("p.md", "human", "prose", MappingProxyType(dict(allow)))


class TestRatchet:
    def test_equal_counts_pass(self) -> None:
        assert rules.ratchet(_entry(**{"absence-prose": 2}), "absence-prose", 2) is None
        assert rules.ratchet(_entry(), "absence-prose", 0) is None

    def test_a_new_violation_fails(self) -> None:
        problem = rules.ratchet(_entry(), "absence-prose", 1)

        assert problem is not None and "1 violating line(s), 0 allowed" in problem

    def test_a_fix_must_lower_the_count(self) -> None:
        problem = rules.ratchet(_entry(**{"absence-prose": 3}), "absence-prose", 1)

        assert problem is not None and "lower its count" in problem

    def test_an_unknown_rule_key_fails(self) -> None:
        problems = rules.allow_problems([_entry(**{"removed-names": 1})])

        assert problems and "unknown rule 'removed-names'" in problems[0]

    def test_a_zero_count_must_be_removed(self) -> None:
        assert rules.allow_problems([_entry(**{"absence-prose": 0})])

    def test_the_default_allow_is_immutable(self) -> None:
        entry = DocEntry("p.md", "human", "prose")

        with pytest.raises(TypeError):
            entry.allow["absence-prose"] = 1  # type: ignore[index]

    def test_the_registry_allow_lists_are_valid(self) -> None:
        assert rules.allow_problems(DOCS) == []


class TestRun:
    @staticmethod
    def _repo(tmp_path: Path, text: str, kind: str = "prose", **allow: int) -> tuple:
        (tmp_path / "p.md").write_text(text, encoding="utf-8")
        entry = DocEntry("p.md", "human", kind, MappingProxyType(dict(allow)))  # type: ignore[arg-type]
        return tmp_path, (entry,)

    FACTS = {rules.UNMEASURED_FACT: Fact(rules.UNMEASURED_FACT, ["callers"], "")}

    def test_a_violation_names_page_line_and_rule(self, tmp_path: Path) -> None:
        root, docs = self._repo(tmp_path, "x\n\nThe symbol doesn't exist.\n")

        problems = rules.run(root, self.FACTS, docs, descriptions={})

        assert "p.md: absence-prose: 1 violating line(s), 0 allowed" in problems
        assert any(p.startswith("p.md:3: absence-prose:") for p in problems)

    def test_an_allowed_violation_passes(self, tmp_path: Path) -> None:
        root, docs = self._repo(tmp_path, "The symbol doesn't exist.\n", **{"absence-prose": 1})

        assert rules.run(root, self.FACTS, docs, descriptions={}) == []

    def test_history_pages_are_exempt(self, tmp_path: Path) -> None:
        root, docs = self._repo(tmp_path, "The symbol doesn't exist.\n", kind="history")

        assert rules.run(root, self.FACTS, docs, descriptions={}) == []

    def test_tool_descriptions_are_scanned_with_no_allowance(self, tmp_path: Path) -> None:
        root, docs = self._repo(tmp_path, "fine\n")

        problems = rules.run(
            root, self.FACTS, docs, descriptions={"t": "Each name that doesn't exist."}
        )

        assert problems and problems[0].startswith("tool:t:1: absence-prose:")

    def test_the_repo_passes_every_rule(self, facts: dict) -> None:
        """The live run, as ``docs_facts check`` does it: registry plus tool descriptions."""
        assert rules.run(ROOT, facts) == []


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
