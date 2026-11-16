"""Tests for duplication review (#495): guards, families, the occurrence cap,
dismissal state, the no-content contract and the CLI.

The ratchet's own behaviour is pinned in ``tests/test_duplicate_code_report.py``;
here we check only that the script now delegates to this core.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest

from pyeye import duplication as dup
from pyeye.architecture_review import state as review_state

_ROOT = Path(__file__).resolve().parents[1]

# A function long enough (>35 tokens) to be reported when copied.
_BODY = """
def {name}(handle, analyzer):
    parts = handle.split(".")
    module_dotted = ".".join(parts[:-1])
    leaf = parts[-1]
    try:
        script = analyzer.make_script(module_dotted, leaf)
        inferred = script.infer(2, len(module_dotted) + 1 + len(leaf))
        for n in inferred:
            if n.full_name == handle:
                return n
    except Exception:
        pass
    return None
"""

# A second, unrelated function body (no 35-token run in common with _BODY).
_OTHER = """
def {name}(rows, limit):
    total = 0
    seen = set()
    while rows and total < limit:
        row = rows.pop()
        if row in seen:
            continue
        seen.add(row)
        total += len(row) * 2
        yield {{"row": row, "total": total}}
    raise StopIteration
"""

# A distinctive token that must never appear in review output (no-content contract).
_MARKER = "zz_marker_only_in_source_zz"


def _write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def _review(root: Path, **kwargs: object) -> dup.Review:
    return dup.review([root], root, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The script delegates to this core
# ---------------------------------------------------------------------------


def test_ratchet_script_uses_the_shared_core() -> None:
    spec = importlib.util.spec_from_file_location(
        "dcr_for_core_test", _ROOT / "scripts" / "duplicate_code_report.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert module.find_clones is dup.find_clones
    assert module.tokenize is dup.tokenize
    assert module.BASELINE == {}


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def test_function_copy_is_a_family(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", _BODY.format(name="find"))
    _write(tmp_path, "b.py", _BODY.format(name="lookup"))
    result = _review(tmp_path)
    assert [f.locations for f in result.families] == [["a.py::find", "b.py::lookup"]]


def test_module_level_data_tables_are_filtered(tmp_path: Path) -> None:
    table = (
        "TABLE = {\n" + "".join(f"    'k{i}': ('v{i}', {i}, None),\n" for i in range(40)) + "}\n"
    )
    _write(tmp_path, "a.py", table)
    _write(tmp_path, "b.py", table.replace("TABLE", "OTHER"))
    assert dup.find_clones(dup.collect([tmp_path], tmp_path)), "the detector sees the copy"
    assert _review(tmp_path).families == [], "the review filters module-level data"


def test_overload_stubs_are_guarded(tmp_path: Path) -> None:
    params = ", ".join(f"p{i}: int | None = None" for i in range(14))
    stubs = "".join(
        f"@overload\ndef make(x: {t}, *, {params}) -> {t}: ...\n" for t in ("int", "str", "bytes")
    )
    _write(tmp_path, "a.py", "from typing import overload\n" + stubs)
    assert dup.find_clones(dup.collect([tmp_path], tmp_path)), "the detector sees the stubs"
    assert _review(tmp_path).families == []


def test_protocol_and_abstract_stub_bodies_are_guarded(tmp_path: Path) -> None:
    method = "    def {n}(self, a: int, b: str, c: float, d: bytes, e: list[int], f: dict[str, int]) -> None:\n        ...\n"
    proto = "class P(Protocol):\n" + "".join(method.format(n=f"m{i}") for i in range(4))
    _write(tmp_path, "a.py", "from typing import Protocol\n" + proto)
    _write(tmp_path, "b.py", "from typing import Protocol\n" + proto.replace("class P", "class Q"))
    assert dup.find_clones(dup.collect([tmp_path], tmp_path))
    assert _review(tmp_path).families == []


def test_a_signature_copy_with_a_real_body_copy_is_kept(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "import functools\n\n@functools.cache" + _BODY.format(name="find"))
    _write(tmp_path, "b.py", "import functools\n\n@functools.cache" + _BODY.format(name="lookup"))
    assert len(_review(tmp_path).families) == 1


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------


def test_copies_between_two_classes_are_one_family(tmp_path: Path) -> None:
    # Two separate copies between the same two classes, kept apart by unrelated code.
    gap_a = "\ndef gap(self):\n    return 1\n"
    gap_b = "\ndef gap(self, x, y):\n    return [x for x in range(y) if x % 3 == 0 or x > y]\n"
    a = "class Url:\n" + textwrap.indent(
        _BODY.format(name="build") + gap_a + _OTHER.format(name="walk"), "    "
    )
    b = "class MultiHostUrl:\n" + textwrap.indent(
        _BODY.format(name="build") + gap_b + _OTHER.format(name="iterate"), "    "
    )
    _write(tmp_path, "a.py", a)
    _write(tmp_path, "b.py", b)
    (family,) = _review(tmp_path).families  # both copies, one family
    assert len(family.sites) == 2
    assert {loc.split("::")[0] for loc in family.locations} == {"a.py", "b.py"}
    assert "a.py::Url.walk" in family.locations
    assert "b.py::MultiHostUrl.iterate" in family.locations


def test_copies_inside_one_class_are_not_merged_by_the_class(tmp_path: Path) -> None:
    body = _BODY.format(name="one") + _BODY.format(name="two")
    body += _OTHER.format(name="three") + _OTHER.format(name="four")
    _write(tmp_path, "a.py", "class Big:\n" + textwrap.indent(body, "    "))
    families = _review(tmp_path).families
    assert sorted(f.locations for f in families) == [
        ["a.py::Big.four", "a.py::Big.three"],
        ["a.py::Big.one", "a.py::Big.two"],
    ]


def test_an_intra_class_copy_of_a_cross_class_member_joins_its_family(tmp_path: Path) -> None:
    a = "class Url:\n" + textwrap.indent(
        _BODY.format(name="build") + _BODY.format(name="rebuild"), "    "
    )
    _write(tmp_path, "a.py", a)
    _write(tmp_path, "b.py", "class Other:\n" + textwrap.indent(_BODY.format(name="build"), "    "))
    (family,) = _review(tmp_path).families
    assert "a.py::Url.rebuild" in family.locations, "the intra-class copy joins the family"
    assert any(loc.startswith("b.py::Other") for loc in family.locations)


def test_family_identity_is_order_independent_and_stable(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", _BODY.format(name="find"))
    _write(tmp_path, "b.py", _BODY.format(name="lookup"))
    (fam,) = _review(tmp_path).families
    assert fam.key == review_state.non_issue_key(["b.py::lookup", "a.py::find"], dup.DISMISSAL_FACT)
    assert fam.id == fam.key.removeprefix("ni:")[:12]


# ---------------------------------------------------------------------------
# Occurrence cap: bounded work, counted (no timing)
# ---------------------------------------------------------------------------


def _table(n: int) -> str:
    return "".join(f"    'name{i}': '\\U0001F600',\n" for i in range(n))


def test_occurrence_cap_bounds_the_pair_loop(tmp_path: Path) -> None:
    _write(tmp_path, "emoji.py", "CODES = {\n" + _table(2000) + "}\n")
    streams = dup.collect([tmp_path], tmp_path)
    stats = dup.FindStats()
    clones = dup.find_clones(streams, 35, dup.DEFAULT_MAX_OCCURRENCES, stats)
    cap = dup.DEFAULT_MAX_OCCURRENCES
    assert stats.skipped_windows >= 1
    assert stats.pairs_examined <= stats.windows * cap * (cap + 1) // 2
    assert stats.pairs_examined < 10_000
    assert len(clones) < 100


def test_without_the_cap_the_same_input_is_quadratic(tmp_path: Path) -> None:
    """The reason for the cap, measured as work on a small input (never a big one)."""
    _write(tmp_path, "emoji.py", "CODES = {\n" + _table(300) + "}\n")
    streams = dup.collect([tmp_path], tmp_path)
    capped, uncapped = dup.FindStats(), dup.FindStats()
    dup.find_clones(streams, 35, dup.DEFAULT_MAX_OCCURRENCES, capped)
    dup.find_clones(streams, 35, 10**9, uncapped)
    assert uncapped.pairs_examined > 20 * capped.pairs_examined


def test_a_real_copy_is_still_found_beside_a_capped_table(tmp_path: Path) -> None:
    _write(tmp_path, "emoji.py", "CODES = {\n" + _table(2000) + "}\n")
    _write(tmp_path, "a.py", _BODY.format(name="find"))
    _write(tmp_path, "b.py", _BODY.format(name="lookup"))
    assert [f.locations for f in _review(tmp_path).families] == [["a.py::find", "b.py::lookup"]]


# ---------------------------------------------------------------------------
# Dismissal state (option A)
# ---------------------------------------------------------------------------


def _dismiss_all(root: Path, state_path: Path, **kwargs: str) -> None:
    state = review_state.load_state(state_path)
    for fam in _review(root).families:
        dup.dismiss(
            state,
            fam,
            kwargs.get("reason", "benign-idiom"),
            "2026-11-17",
            kwargs.get("review_after"),
        )
    review_state.save_state(state_path, state)


def _shown(root: Path, state_path: Path, today: str | None = None) -> dup.Review:
    state = review_state.load_state(state_path)
    return dup.review([root], root, dismissals=state["confirmed_non_issues"], today=today)


@pytest.fixture
def dismissed(tmp_path: Path) -> tuple[Path, Path]:
    src = tmp_path / "src"
    _write(src, "a.py", _BODY.format(name="find"))
    _write(src, "b.py", _BODY.format(name="lookup"))
    state_path = tmp_path / ".pyeye" / "duplication-review.json"
    state_path.parent.mkdir()
    _dismiss_all(src, state_path)
    return src, state_path


def test_dismissal_round_trips_and_suppresses(dismissed: tuple[Path, Path]) -> None:
    src, state_path = dismissed
    (entry,) = review_state.load_state(state_path)["confirmed_non_issues"]
    assert entry["structural_fact"] == "duplication"
    assert entry["handles"] == ["a.py::find", "b.py::lookup"]
    assert entry["key"] == review_state.non_issue_key(entry["handles"], "duplication")
    assert entry["reason"] == "benign-idiom" and entry["dismissed_on"] == "2026-11-17"
    result = _shown(src, state_path)
    assert result.families == [] and len(result.suppressed) == 1


def test_cosmetic_edits_and_drift_stay_suppressed(dismissed: tuple[Path, Path]) -> None:
    src, state_path = dismissed
    _write(
        src,
        "a.py",
        "# moved down\n\n\n" + _BODY.format(name="find").replace("pass", "pass  # drift"),
    )
    _write(src, "b.py", _BODY.format(name="lookup").replace('"."', '"/"'))  # drift between members
    assert _shown(src, state_path).families == []


def test_a_member_removed_stays_suppressed(dismissed: tuple[Path, Path]) -> None:
    src, state_path = dismissed
    _write(src, "c.py", _BODY.format(name="third"))
    _dismiss_all(src, state_path)  # the three-member family is dismissed too
    (src / "c.py").unlink()
    assert _shown(src, state_path).families == []


def test_a_new_member_resurfaces_showing_only_it(dismissed: tuple[Path, Path]) -> None:
    src, state_path = dismissed
    _write(src, "c.py", _BODY.format(name="third"))
    (fam,) = _shown(src, state_path).families
    assert fam.status == "resurfaced"
    assert fam.new_locations == ["c.py::third"]
    shown = fam.as_dict()["sites"]
    assert shown and all("c.py" in (s["a"]["file"], s["b"]["file"]) for s in shown)
    assert "1 new member(s) of a dismissed family" in dup.format_review(_shown(src, state_path))


def test_a_rename_resurfaces(dismissed: tuple[Path, Path]) -> None:
    src, state_path = dismissed
    _write(src, "b.py", _BODY.format(name="lookup_renamed"))
    (fam,) = _shown(src, state_path).families
    assert fam.status == "resurfaced" and fam.new_locations == ["b.py::lookup_renamed"]


def test_a_move_resurfaces(dismissed: tuple[Path, Path]) -> None:
    src, state_path = dismissed
    (src / "b.py").rename(src / "moved.py")
    (fam,) = _shown(src, state_path).families
    assert fam.new_locations == ["moved.py::lookup"]


def test_re_dismissing_a_resurfaced_family_leaves_one_entry(dismissed: tuple[Path, Path]) -> None:
    src, state_path = dismissed
    _write(src, "c.py", _BODY.format(name="third"))
    _dismiss_all(src, state_path, reason="deliberate-twin")
    (entry,) = review_state.load_state(state_path)["confirmed_non_issues"]
    assert entry["handles"] == ["a.py::find", "b.py::lookup", "c.py::third"]
    assert _shown(src, state_path).families == []


def test_review_after_resurfaces_only_once_due(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _write(src, "a.py", _BODY.format(name="find"))
    _write(src, "b.py", _BODY.format(name="lookup"))
    state_path = tmp_path / "state.json"
    _dismiss_all(src, state_path, review_after="2027-01-01")
    assert _shown(src, state_path, today="2026-12-31").families == []
    assert _shown(src, state_path).families == [], "no today: nothing is due (no clock)"
    (fam,) = _shown(src, state_path, today="2027-01-01").families
    assert fam.status == "review-due" and fam.dismissal["review_after"] == "2027-01-01"


def test_no_expiry_by_default(dismissed: tuple[Path, Path]) -> None:
    src, state_path = dismissed
    assert _shown(src, state_path, today="2099-12-31").families == []


def test_architecture_review_non_issues_are_ignored(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", _BODY.format(name="find"))
    _write(tmp_path, "b.py", _BODY.format(name="lookup"))
    other = {"handles": ["a.py::find", "b.py::lookup"], "structural_fact": "facet:layering/x"}
    assert len(dup.review([tmp_path], tmp_path, dismissals=[other]).families) == 1


@pytest.mark.parametrize(
    ("reason", "date", "review_after", "match"),
    [
        ("because", "2026-11-17", None, "reason"),
        ("vendored", "17/11/2026", None, "--date"),
        ("vendored", "2026-11-17", "soon", "--review-after"),
    ],
)
def test_dismiss_validates_its_inputs(
    tmp_path: Path, reason: str, date: str, review_after: str | None, match: str
) -> None:
    _write(tmp_path, "a.py", _BODY.format(name="find"))
    _write(tmp_path, "b.py", _BODY.format(name="lookup"))
    (fam,) = _review(tmp_path).families
    with pytest.raises(ValueError, match=match):
        dup.dismiss({}, fam, reason, date, review_after)


# ---------------------------------------------------------------------------
# No source content; judgment labelling
# ---------------------------------------------------------------------------


def test_output_is_pointers_only_and_labelled_a_judgment(tmp_path: Path) -> None:
    body = _BODY.replace('"."', f'"{_MARKER}"')
    _write(tmp_path, "a.py", body.format(name="find"))
    _write(tmp_path, "b.py", body.format(name="lookup"))
    result = _review(tmp_path)
    text, data = dup.format_review(result), json.dumps(result.as_dict())
    for out in (text, data):
        assert _MARKER not in out
        assert "make_script" not in out, "no source text, only qualnames and line ranges"
    payload = result.as_dict()
    assert payload["judgment"] is True and payload["min_tokens"] == 35
    assert payload["max_occurrences"] == 50 and payload["filters"]
    assert "Judgment, not fact" in text


def test_scope_is_required(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="scope is required"):
        dup.review([], tmp_path)
    with pytest.raises(SystemExit):
        dup.main(["review"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_review_and_dismiss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path, "pkg/a.py", _BODY.format(name="find"))
    _write(tmp_path, "pkg/b.py", _BODY.format(name="lookup"))
    monkeypatch.chdir(tmp_path)
    state = Path(".pyeye/duplication-review.json")
    assert dup.main(["review", "pkg", "--json", "--state", str(state)]) == 0
    (fam,) = json.loads(capsys.readouterr().out)["families"]
    assert fam["locations"] == ["pkg/a.py::find", "pkg/b.py::lookup"]
    args = ["dismiss", "pkg", "--state", str(state), "--family", fam["id"]]
    assert dup.main([*args, "--reason", "deliberate-twin", "--date", "2026-11-17"]) == 0
    assert state.exists()
    capsys.readouterr()
    assert dup.main(["review", "pkg", "--state", str(state)]) == 0
    out = capsys.readouterr().out
    assert "0 families" in out and "1 dismissed and suppressed" in out


def test_cli_dismiss_unknown_family_and_missing_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "pkg/a.py", _BODY.format(name="find"))
    monkeypatch.chdir(tmp_path)
    base = ["dismiss", "pkg", "--family", "nope", "--reason", "other", "--date", "2026-11-17"]
    assert dup.main(base) == 2
    assert dup.main([*base, "--state", "s.json"]) == 1


def test_cli_rejects_a_bad_today(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "x = 1\n")
    with pytest.raises(ValueError, match="--today"):
        dup.main(["review", str(tmp_path), "--today", "tomorrow"])
