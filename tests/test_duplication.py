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
from typing import Any

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


def _load_ratchet() -> Any:
    spec = importlib.util.spec_from_file_location(
        "dcr_for_core_test", _ROOT / "scripts" / "duplicate_code_report.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_ratchet_script_uses_the_shared_core() -> None:
    module = _load_ratchet()
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


def test_occurrence_cap_keeps_the_pair_loop_linear(tmp_path: Path) -> None:
    _write(tmp_path, "emoji.py", "CODES = {\n" + _table(2000) + "}\n")
    streams = dup.collect([tmp_path], tmp_path)
    positions = sum(max(0, len(s) - 35 + 1) for s in streams)
    stats = dup.FindStats()
    dup.find_clones(streams, 35, dup.DEFAULT_MAX_OCCURRENCES, stats)
    assert stats.capped_windows >= 1
    # Capped windows pair each occurrence with the next one: at most one pair
    # per indexed position, never k * (k - 1) / 2.
    assert stats.pairs_examined <= positions


def test_without_the_cap_the_same_input_is_quadratic(tmp_path: Path) -> None:
    """The reason for the cap, measured as work on a small input (never a big one)."""
    _write(tmp_path, "emoji.py", "CODES = {\n" + _table(300) + "}\n")
    streams = dup.collect([tmp_path], tmp_path)
    capped, uncapped = dup.FindStats(), dup.FindStats()
    dup.find_clones(streams, 35, dup.DEFAULT_MAX_OCCURRENCES, capped)
    dup.find_clones(streams, 35, 10**9, uncapped)
    assert uncapped.pairs_examined > 20 * capped.pairs_examined


@pytest.mark.parametrize("copies", [50, 51, 120])
def test_a_block_copied_past_the_cap_is_still_one_family(tmp_path: Path, copies: int) -> None:
    """Review #2: 51 copies used to vanish (0 clones) where 50 gave 1,225."""
    for i in range(copies):
        _write(tmp_path, f"f{i:03d}.py", _BODY.format(name=f"g{i}"))
    (family,) = _review(tmp_path).families
    assert len(family.locations) == copies


def test_past_the_cap_the_work_is_linear_in_copies(tmp_path: Path) -> None:
    for i in range(120):
        _write(tmp_path, f"f{i:03d}.py", _BODY.format(name=f"g{i}"))
    stats = dup.FindStats()
    clones = dup.find_clones(dup.collect([tmp_path], tmp_path), 35, 50, stats)
    assert len(clones) == 119, "a chain of copies, not 7,140 pairs"
    assert stats.pairs_examined <= stats.capped_windows * 119


def test_find_clones_rejects_degenerate_thresholds() -> None:
    with pytest.raises(ValueError, match="min_tokens"):
        dup.find_clones([], 0)
    with pytest.raises(ValueError, match="max_occurrences"):
        dup.find_clones([], 35, 1)


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


def test_cli_exit_2_comes_before_the_scan_and_exit_1_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """#882: main's docstring names both exits; pin which side of the scan each is on."""
    _write(tmp_path, "pkg/a.py", _BODY.format(name="find"))
    monkeypatch.chdir(tmp_path)
    scans: list[object] = []
    real_review = dup.review
    monkeypatch.setattr(dup, "review", lambda *a, **k: scans.append(a) or real_review(*a, **k))
    base = ["dismiss", "pkg", "--family", "nope", "--reason", "other", "--date", "2026-11-17"]

    assert dup.main(base) == 2  # no --state: a bad argument
    assert dup.main([*base, "--state", "s.json", "--date", "someday"]) == 2  # a bad date
    assert scans == [], "an exit-2 error must not scan"

    assert dup.main([*base, "--state", "s.json"]) == 1
    assert len(scans) == 1, "an unknown family is only known after the scan"
    assert "no family with id 'nope'" in capsys.readouterr().err
    assert not (tmp_path / "s.json").exists()


def test_cli_rejects_a_bad_today(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path, "a.py", "x = 1\n")
    assert dup.main(["review", str(tmp_path), "--root", str(tmp_path), "--today", "tomorrow"]) == 2
    assert "--today" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Regressions from the #820 review
# ---------------------------------------------------------------------------


def test_a_region_is_named_after_the_scope_holding_most_of_it(tmp_path: Path) -> None:
    """Review #1: a copy starting in the previous function's tail was named after it."""
    _write(tmp_path, "m.py", "def prev_m(q):\n    return q\n" + _BODY.format(name="one"))
    _write(
        tmp_path, "x.py", "def prev_x(s):\n    s = s + 1\n    return s\n" + _BODY.format(name="x1")
    )
    (family,) = _review(tmp_path).families
    assert family.locations == ["m.py::one", "x.py::x1"]


def test_editing_the_previous_function_keeps_the_dismissal(tmp_path: Path) -> None:
    """Review #1, identity: the unrelated neighbour can change without re-surfacing."""
    _write(tmp_path, "m.py", "def prev_m(q):\n    return q\n" + _BODY.format(name="one"))
    _write(tmp_path, "x.py", "def prev_x(s):\n    return s\n" + _BODY.format(name="x1"))
    state_path = tmp_path / "state.json"
    _dismiss_all(tmp_path, state_path)
    _write(tmp_path, "m.py", "def renamed_neighbour(q):\n    return q\n" + _BODY.format(name="one"))
    assert _shown(tmp_path, state_path).families == []


def test_unparseable_files_are_skipped_and_named_without_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review #3: a SyntaxError printed the source line; non-UTF-8 crashed."""
    _write(tmp_path, "bad.py", f"def f(:\n    {_MARKER} = 1\n")
    (tmp_path / "latin.py").write_bytes(b"x = '\xe9'\n")
    _write(tmp_path, "a.py", _BODY.format(name="find"))
    _write(tmp_path, "b.py", _BODY.format(name="lookup"))
    assert dup.main(["review", str(tmp_path), "--root", str(tmp_path), "--json"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["unparseable_files"] == ["bad.py", "latin.py"]
    assert len(payload["families"]) == 1, "the parseable files are still reviewed"
    assert _MARKER not in captured.out + captured.err
    assert dup.main(["review", str(tmp_path), "--root", str(tmp_path)]) == 0
    text = capsys.readouterr()
    assert "unparseable (skipped): bad.py; latin.py" in text.out
    assert _MARKER not in text.out + text.err


def test_ratchet_fails_on_an_unparseable_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _load_ratchet()
    _write(tmp_path, "bad.py", "def f(:\n")
    assert script.main([str(tmp_path / "bad.py"), "--root", str(tmp_path)]) == 1
    assert "unparseable (not checked): bad.py" in capsys.readouterr().out


def test_ratchet_catches_a_copy_made_past_the_cap(tmp_path: Path) -> None:
    """Review #9: with the cap a 51-way copy must still fail the ratchet."""
    script = _load_ratchet()
    for i in range(51):
        _write(tmp_path, f"f{i:02d}.py", _BODY.format(name=f"g{i}"))
    assert script.main([str(tmp_path), "--root", str(tmp_path)]) == 1


def test_a_concrete_method_of_an_abc_is_not_a_stub(tmp_path: Path) -> None:
    """Review #4: every method of an ABC/Protocol class was treated as a stub."""
    method = textwrap.indent(
        _BODY.format(name="helper").replace("(handle", "(self, handle"), "    "
    )
    _write(tmp_path, "a.py", "from abc import ABC\nclass A(ABC):\n" + method)
    _write(tmp_path, "b.py", "from typing import Protocol\nclass B(Protocol):\n" + method)
    assert len(_review(tmp_path).families) == 1


def test_an_abstractmethod_with_a_body_is_still_a_stub(tmp_path: Path) -> None:
    method = textwrap.indent(
        _BODY.format(name="helper").replace("(handle", "(self, handle"), "    "
    )
    abstract = method.replace("    def helper", "    @abstractmethod\n    def helper")
    head = "from abc import ABCMeta, abstractmethod\nclass {n}(metaclass=ABCMeta):\n"
    _write(tmp_path, "a.py", head.format(n="A") + abstract)
    _write(tmp_path, "b.py", head.format(n="B") + abstract)
    assert _review(tmp_path).families == []


def test_module_level_regions_of_one_file_are_not_merged(tmp_path: Path) -> None:
    """Review #5: every module-level region of a file shared one ``<module>`` node."""

    def module_level(body: str) -> str:
        lines = body.strip("\n").splitlines()[1:]  # drop the def line
        return textwrap.dedent("\n".join(lines)).replace("return None", "result = None")

    first = module_level(_BODY.format(name="x")).replace("return n", "result = n")
    second = (
        module_level(_OTHER.format(name="y"))
        .replace("yield", "print")
        .replace("raise StopIteration", "result = total")
    )
    _write(
        tmp_path,
        "m.py",
        "handle = analyzer = None\n" + first + "\n\nrows, limit = [], 1\n" + second + "\n",
    )
    _write(tmp_path, "a.py", _BODY.format(name="f2"))
    _write(
        tmp_path,
        "b.py",
        _OTHER.format(name="g2")
        .replace("yield", "print")
        .replace("raise StopIteration", "result = total"),
    )
    families = _review(tmp_path).families
    assert all(len(f.locations) == 2 for f in families), [f.locations for f in families]


def test_a_class_to_function_pair_is_not_folded(tmp_path: Path) -> None:
    """Review #5: folding unioned class-to-function pairs into one family."""
    method_m = _BODY.format(name="m").replace("(handle", "(self, handle")
    method_k = _OTHER.format(name="k").replace("(rows", "(self, rows")
    _write(tmp_path, "a.py", "class C:\n" + textwrap.indent(method_m + method_k, "    "))
    _write(tmp_path, "b.py", _BODY.format(name="f"))
    _write(tmp_path, "c.py", _OTHER.format(name="g"))
    families = sorted(f.locations for f in _review(tmp_path).families)
    assert families == [["a.py::C.k", "c.py::g"], ["a.py::C.m", "b.py::f"]]


def test_a_copy_bridging_two_dismissed_families_resurfaces_naming_the_bridge(
    tmp_path: Path,
) -> None:
    """Review #6: the bridge re-surfaced with "0 new member(s)" and wasn't shown."""
    _write(tmp_path, "a.py", _BODY.format(name="fa"))
    _write(tmp_path, "b.py", _BODY.format(name="fb"))
    _write(tmp_path, "c.py", _OTHER.format(name="gc"))
    _write(tmp_path, "e.py", _OTHER.format(name="ge"))
    state_path = tmp_path / "state.json"
    _dismiss_all(tmp_path, state_path)
    assert len(review_state.load_state(state_path)["confirmed_non_issues"]) == 2
    # One function now holds both copied blocks: a.py::fa joins gc/ge's family.
    _write(
        tmp_path,
        "a.py",
        _BODY.format(name="fa").replace(
            "    return None",
            "    return None\n" + textwrap.indent(_OTHER.format(name="inner"), "    "),
        ),
    )
    shown = _shown(tmp_path, state_path).families
    bridged = [f for f in shown if f.status == "resurfaced"]
    assert bridged, [(f.status, f.locations) for f in shown]
    fam = bridged[0]
    assert fam.new_sites and fam.as_dict()["sites"]
    assert all(
        not any(
            set(s.locations) <= set(d["handles"])
            for d in review_state.load_state(state_path)["confirmed_non_issues"]
        )
        for s in fam.new_sites
    )
    assert "new site(s)" in dup.format_review(_shown(tmp_path, state_path))


def test_the_same_qualname_twice_in_one_file_is_one_location(tmp_path: Path) -> None:
    """Review #10: if/else twins share a qualname; they are one location, two ranges."""
    twins = "import sys\nif sys.platform == 'win32':\n" + textwrap.indent(
        _BODY.format(name="f"), "    "
    )
    twins += "else:\n" + textwrap.indent(_BODY.format(name="f"), "    ")
    _write(tmp_path, "m.py", twins)
    (family,) = _review(tmp_path).families
    assert family.locations == ["m.py::f"]
    (site,) = family.sites
    assert site.a.start != site.b.start
    state_path = tmp_path / "state.json"
    _dismiss_all(tmp_path, state_path, reason="deliberate-twin")
    assert _shown(tmp_path, state_path).families == []


@pytest.mark.parametrize(
    ("content", "match"),
    [
        ("{bad", "not readable JSON"),
        ("[1]", "must hold a JSON object"),
        ('{"confirmed_non_issues": {}}', "must be a list"),
        ('{"confirmed_non_issues": [{"structural_fact": "duplication"}]}', "list of handles"),
        (
            '{"confirmed_non_issues": [{"handles": [], "structural_fact": "duplication", '
            '"review_after": "soon"}]}',
            "review_after",
        ),
    ],
)
def test_a_bad_state_file_exits_2_with_a_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str, match: str
) -> None:
    """Review #7: bad state gave tracebacks."""
    _write(tmp_path, "a.py", "x = 1\n")
    (tmp_path / "s.json").write_text(content, encoding="utf-8")
    args = ["review", str(tmp_path), "--root", str(tmp_path), "--state", str(tmp_path / "s.json")]
    assert dup.main(args) == 2
    err = capsys.readouterr().err
    assert match in err and "Traceback" not in err


@pytest.mark.parametrize(
    ("extra", "match"),
    [
        (["--min-tokens", "0"], "--min-tokens"),
        (["--max-occurrences", "1"], "--max-occurrences"),
    ],
)
def test_bad_thresholds_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: list[str], match: str
) -> None:
    _write(tmp_path, "a.py", "x = 1\n")
    assert dup.main(["review", str(tmp_path), "--root", str(tmp_path), *extra]) == 2
    assert match in capsys.readouterr().err


def test_bad_dismiss_dates_are_rejected_before_scanning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review #7: a bad --date was only noticed after the full scan."""
    _write(tmp_path, "a.py", "x = 1\n")

    def no_scan(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("scanned before validating")

    monkeypatch.setattr(dup, "collect", no_scan)
    base = ["dismiss", str(tmp_path), "--root", str(tmp_path), "--state", str(tmp_path / "s.json")]
    base += ["--family", "x", "--reason", "other"]
    assert dup.main([*base, "--date", "17/11/2026"]) == 2
    assert dup.main([*base, "--date", "2026-11-17", "--review-after", "later"]) == 2
    err = capsys.readouterr().err
    assert "--date" in err and "--review-after" in err


def test_a_scope_outside_root_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review #8: a file outside --root got an absolute, unshareable key."""
    inside, outside = tmp_path / "proj", tmp_path / "elsewhere"
    _write(inside, "a.py", "x = 1\n")
    _write(outside, "b.py", "x = 1\n")
    assert dup.main(["review", str(outside), "--root", str(inside)]) == 2
    assert "outside --root" in capsys.readouterr().err
    with pytest.raises(ValueError, match="outside --root"):
        dup.review([outside], inside)


def test_a_missing_scope_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        dup.review([tmp_path / "nope"], tmp_path)


# ---------------------------------------------------------------------------
# Regressions from the #820 re-review
# ---------------------------------------------------------------------------

_SMALL = "def small(self, q):\n    return [q * 2 for _ in range(q) if q]\n"


def _whole_class(name: str, comments: int = 0) -> str:
    small = _SMALL.replace(
        "    return", "".join(f"    # note {i}\n" for i in range(comments)) + "    return"
    )
    big = _BODY.format(name="big").replace("(handle", "(self, handle")
    return f"class {name}:\n" + textwrap.indent(small + big, "    ")


def test_a_comment_only_edit_keeps_the_location(tmp_path: Path) -> None:
    """Re-review B: naming counted physical lines, so comments could rename a site."""
    _write(tmp_path, "a.py", _whole_class("A"))
    _write(tmp_path, "b.py", _whole_class("B"))
    (before,) = _review(tmp_path).families
    state_path = tmp_path / "state.json"
    _dismiss_all(tmp_path, state_path)
    _write(tmp_path, "a.py", _whole_class("A", comments=40))
    (after,) = _review(tmp_path).families
    assert after.locations == before.locations
    assert _shown(tmp_path, state_path).families == [], "a comment-only edit must not re-surface"


def _many_runs_per_offset(root: Path, files: int, statements: int) -> None:
    """Files identical but for a line every 6 statements: many runs per offset."""
    for j in range(files):
        lines = [
            (
                f"    y = z.only_in_file_{j}\n"
                if i % 6 == 5
                else f"    x = helper(a, b[{i}], c.attr_{i}(d, e), [f for f in g if f > {i}])\n"
            )
            for i in range(statements)
        ]
        _write(
            root, f"f{j:02d}.py", "def big(a, b, c, d, e, g):\n" + "".join(lines) + "    return a\n"
        )


def test_coverage_is_one_bounded_lookup_per_pair(tmp_path: Path) -> None:
    """Re-review A: the covered check scanned a growing list per pair."""
    _many_runs_per_offset(tmp_path, files=4, statements=180)
    stats = dup.FindStats()
    dup.find_clones(dup.collect([tmp_path], tmp_path), 35, 50, stats)
    assert stats.max_intervals >= 25, "the input holds many disjoint runs per offset"
    # One bisect per pair; a linear scan would cost up to max_intervals per pair.
    assert stats.coverage_steps == stats.pairs_examined


def test_intervals_merge_and_answer_membership() -> None:
    ivs = dup._Intervals()
    ivs.add(10, 12)
    ivs.add(20, 25)
    ivs.add(13, 19)  # touches both: one interval
    assert len(ivs) == 1 and all(n in ivs for n in (10, 16, 25)) and 9 not in ivs and 26 not in ivs
    ivs.add(1, 2)
    ivs.add(30, 31)
    assert len(ivs) == 3 and 3 not in ivs and 30 in ivs and "x" not in ivs


def test_a_location_is_in_exactly_one_family(tmp_path: Path) -> None:
    """Re-review C: Base.helper landed in a class family and a plain one."""
    helper = _BODY.format(name="helper").replace("(handle", "(self, handle")
    _write(tmp_path, "base.py", "class Base:\n" + textwrap.indent(helper, "    "))
    _write(tmp_path, "other.py", "class Other:\n" + textwrap.indent(helper, "    "))
    _write(tmp_path, "m.py", _BODY.format(name="one"))
    families = _review(tmp_path).families
    seen = [loc for f in families for loc in f.locations]
    assert len(seen) == len(set(seen)), [f.locations for f in families]
    (family,) = families
    assert family.locations == ["base.py::Base.helper", "m.py::one", "other.py::Other.helper"]


def test_a_function_site_folds_only_a_cross_class_method_end(tmp_path: Path) -> None:
    """#882: the function end stays itself; the method end folds only if it is cross-class."""
    helper = _BODY.format(name="helper").replace("(handle", "(self, handle")
    # Base.helper is in no cross-class pair: the function copy stays its own family.
    _write(tmp_path, "base.py", "class Base:\n" + textwrap.indent(helper, "    "))
    _write(tmp_path, "m.py", _BODY.format(name="one"))
    (family,) = _review(tmp_path).families
    assert family.locations == ["base.py::Base.helper", "m.py::one"]
    assert len(family.sites) == 1

    # Once Base.helper is also copied into another class, its end is that class
    # family's node, so the function copy joins the class family: still one family.
    _write(tmp_path, "other.py", "class Other:\n" + textwrap.indent(helper, "    "))
    families = _review(tmp_path).families
    assert [f.locations for f in families] == [
        ["base.py::Base.helper", "m.py::one", "other.py::Other.helper"]
    ]


def test_module_level_code_never_links_unrelated_dismissals() -> None:
    """Re-review: families sharing ``file::<module>`` touched each other's dismissals."""
    fam_a = dup.Family(
        [dup.Site(dup.Region("m.py", 1, 9, "<module>"), dup.Region("a.py", 1, 9, "f"), 40, 1)]
    )
    fam_b = dup.Family(
        [dup.Site(dup.Region("m.py", 30, 39, "<module>"), dup.Region("b.py", 1, 9, "g"), 40, 1)]
    )
    state: dict[str, Any] = {"confirmed_non_issues": []}
    dup.dismiss(state, fam_a, "benign-idiom", "2026-11-17")
    shown, suppressed = dup.apply_dismissals([fam_a, fam_b], state["confirmed_non_issues"])
    assert suppressed == [fam_a]
    assert [(f.status, f.dismissal) for f in shown] == [("new", None)]


@pytest.mark.parametrize(
    ("entry", "match"),
    [
        (
            '{"handles": ["a::b"], "structural_fact": "duplication", "review_after": 5}',
            "must be a string",
        ),
        (
            '{"handles": ["a::b"], "structural_fact": "duplication", "dismissed_on": []}',
            "must be a string",
        ),
        ('{"handles": [1], "structural_fact": "duplication"}', "list of handles"),
    ],
)
def test_non_string_state_values_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], entry: str, match: str
) -> None:
    """Re-review D: a numeric review_after raised TypeError past the ValueError handler."""
    _write(tmp_path, "a.py", "x = 1\n")
    (tmp_path / "s.json").write_text('{"confirmed_non_issues": [' + entry + "]}", encoding="utf-8")
    args = ["review", str(tmp_path), "--root", str(tmp_path), "--state", str(tmp_path / "s.json")]
    assert dup.main(args) == 2
    err = capsys.readouterr().err
    assert match in err and "Traceback" not in err


def test_the_declared_commands_match_the_parser() -> None:
    """``COMMANDS`` is what docs-facts reads (#1098); the parser must agree with it."""
    import argparse

    from pyeye import duplication

    built: dict[str, tuple[str, ...]] = {}
    for action in duplication._parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            for command, sub in action.choices.items():
                built[command] = tuple(
                    flag
                    for option in sub._actions
                    for flag in option.option_strings
                    if flag.startswith("--") and flag != "--help"
                )
    assert built == duplication.COMMANDS
