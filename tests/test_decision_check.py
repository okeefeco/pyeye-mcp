"""``decisions check --resolve`` resolves every Anchor and Applies-to reference with pyeye (#1182).

A decision names the code its rule governs. Before #1182 ``check`` validated
only the format, so a rename or deletion left a decision governing nothing,
with no warning. Now, for ACTIVE entries (superseded and amended ones are
history):

- a ``handle`` (rooted at a project package or module) must resolve through
  pyeye, re-exports included, and a repo path (``tests/x.py``) must exist;
  otherwise it fails with ``entry:line``;
- an ``external`` (stdlib or environment) that doesn't resolve is listed,
  never a failure;
- a ``short_form`` (``JediAnalyzer.find_importers``) can't be checked without
  a guess: it fails in entries dated on or after the gate date, and older
  ones are counted on every run, so the remainder stays visible.

The resolving check runs in CI only (22.6 s on this repo, #1182's
measurement); ``--resolve`` without pyeye importable fails, never passes.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from pyeye import decisions
from pyeye.decision_check import resolve_check

GATE = "2026-11-24"


def _entry(
    root: Path,
    name: str,
    *,
    anchor: str,
    applies_to: str,
    status: str = "active",
    amended_by: list[str] | None = None,
) -> None:
    date = name[:10]
    title = name.removesuffix(".md")
    meta = {
        "date": date,
        "title": title,
        "issues": [1],
        "anchors": ["pkg.impl.Thing"],
        "status": status,
        "amends": [],
        "supersedes": [],
        "amended_by": amended_by or [],
        "superseded_by": [],
    }
    front = "\n".join(f"{k}: {json.dumps(v)}" for k, v in meta.items())
    body = (
        f"## {date} — {title}\n\n"
        "**Friction:** something.\n\n"
        "**Decision:** something else, naming `pkg.impl.Gone` in prose that isn't checked.\n\n"
        f"**Anchor:** {anchor}\n\n"
        f"**Applies-to:**\n\n{applies_to}\n\n"
        "**Verify:** unverifiable — a fixture.\n"
    )
    path = root / "docs" / "decisions" / "entries" / name
    path.write_text(f"---\n{front}\n---\n\n{body}", encoding="utf-8")


def _line_of(root: Path, name: str, text: str) -> int:
    lines = (root / "docs" / "decisions" / "entries" / name).read_text(encoding="utf-8")
    return next(i for i, line in enumerate(lines.split("\n"), 1) if text in line)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from pkg.impl import Thing\n", encoding="utf-8")
    (pkg / "impl.py").write_text(
        "class Thing:\n    def go(self) -> None:\n        pass\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    (tmp_path / "docs" / "decisions" / "entries").mkdir(parents=True)
    return tmp_path


def _check(root: Path, gate: str | None = GATE) -> object:
    entries, errors = decisions.load(root / "docs" / "decisions" / "entries")
    assert errors == []
    return resolve_check(entries, root / "docs" / "decisions" / "entries", root, gate)


class TestWhatFails:
    def test_resolving_references_pass(self, repo: Path) -> None:
        _entry(
            repo,
            "2026-01-01-1-ok.md",
            anchor="`pkg.impl.Thing`, `pkg.impl.Thing.go`",
            applies_to="- `pkg.Thing` (a re-export); `tests/test_x.py::test_x`",
        )

        report = _check(repo)

        assert report.problems == []  # type: ignore[attr-defined]

    def test_a_removed_handle_fails_with_entry_and_line(self, repo: Path) -> None:
        name = "2026-01-01-1-stale.md"
        _entry(repo, name, anchor="`pkg.impl.Thing`", applies_to="- `pkg.impl.Gone`")

        report = _check(repo)

        line = _line_of(repo, name, "- `pkg.impl.Gone`")  # the Applies-to item, not the prose
        assert report.problems == [  # type: ignore[attr-defined]
            f"{name}:{line}: Applies-to `pkg.impl.Gone` doesn't resolve (unresolved)"
        ]

    def test_a_removed_file_fails(self, repo: Path) -> None:
        name = "2026-01-01-1-file.md"
        _entry(repo, name, anchor="`tests/test_gone.py`", applies_to="- `pkg.impl.Thing`")

        report = _check(repo)

        line = _line_of(repo, name, "`tests/test_gone.py`")
        assert report.problems == [  # type: ignore[attr-defined]
            f"{name}:{line}: Anchor `tests/test_gone.py` doesn't exist"
        ]

    def test_prose_outside_anchor_and_applies_to_is_not_checked(self, repo: Path) -> None:
        """The fixture's Decision line names `pkg.impl.Gone`: only the two fields count."""
        _entry(repo, "2026-01-01-1-ok.md", anchor="`pkg.impl.Thing`", applies_to="none (policy)")

        assert _check(repo).problems == []  # type: ignore[attr-defined]


class TestOnlyActiveEntries:
    def test_an_amended_entry_is_history(self, repo: Path) -> None:
        _entry(
            repo,
            "2026-01-01-1-old.md",
            anchor="`pkg.impl.Gone`",
            applies_to="- `pkg.impl.Gone`",
            status="amended",
            amended_by=["2026-01-02-1-new.md"],
        )

        report = _check(repo)

        assert report.problems == []  # type: ignore[attr-defined]
        assert report.checked_entries == 0  # type: ignore[attr-defined]


class TestShortForms:
    def test_an_old_short_form_is_counted_not_failed(self, repo: Path) -> None:
        _entry(repo, "2026-01-01-1-old.md", anchor="`impl.Thing`", applies_to="- `Thing.go`")

        report = _check(repo)

        assert report.problems == []  # type: ignore[attr-defined]
        assert report.grandfathered_short_forms == 2  # type: ignore[attr-defined]

    @pytest.mark.parametrize("name", [f"{GATE}-1-new.md", "2027-01-01-1-new.md"])
    def test_a_short_form_on_or_after_the_gate_fails(self, repo: Path, name: str) -> None:
        _entry(repo, name, anchor="`pkg.impl.Thing`", applies_to="- `Thing.go`")

        report = _check(repo)

        line = _line_of(repo, name, "`Thing.go`")
        assert report.problems == [  # type: ignore[attr-defined]
            f"{name}:{line}: Applies-to `Thing.go` is a short form; write it in full "
            "from its package (e.g. `pkg.mod.Name`)"
        ]

    def test_a_bare_file_name_is_a_short_form(self, repo: Path) -> None:
        _entry(repo, f"{GATE}-1-new.md", anchor="`impl.py`", applies_to="- `pkg.impl.Thing`")

        assert "short form" in _check(repo).problems[0]  # type: ignore[attr-defined]

    def test_without_a_gate_no_short_form_fails(self, repo: Path) -> None:
        _entry(repo, "2027-01-01-1-new.md", anchor="`pkg.impl.Thing`", applies_to="- `Thing.go`")

        report = _check(repo, gate=None)

        assert report.problems == []  # type: ignore[attr-defined]
        assert report.grandfathered_short_forms == 1  # type: ignore[attr-defined]


class TestExternals:
    def test_a_resolving_external_passes(self, repo: Path) -> None:
        _entry(repo, "2026-01-01-1-ext.md", anchor="`os.path.join`", applies_to="none (policy)")

        report = _check(repo)

        assert report.problems == []  # type: ignore[attr-defined]
        assert report.unresolved_externals == []  # type: ignore[attr-defined]

    def test_an_unresolved_external_is_listed_not_failed(self, repo: Path) -> None:
        name = "2026-01-01-1-ext.md"
        _entry(repo, name, anchor="`os.no_such_name`", applies_to="none (policy)")

        report = _check(repo)

        line = _line_of(repo, name, "`os.no_such_name`")
        assert report.problems == []  # type: ignore[attr-defined]
        assert report.unresolved_externals == [  # type: ignore[attr-defined]
            f"{name}:{line}: Anchor `os.no_such_name`"
        ]


def _main(repo: Path, *args: str, gate: str | None = GATE) -> int:
    return decisions.main(
        ["--decisions-dir", (repo / "docs" / "decisions").as_posix(), *args],
        short_forms_fail_from=gate,
    )


class TestTheCommand:
    def test_resolve_passes_and_prints_the_short_form_count(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _entry(repo, "2026-01-01-1-ok.md", anchor="`pkg.impl.Thing`", applies_to="none (p)")

        code = _main(repo, "check", "--resolve", "--project-root", repo.as_posix())

        out = capsys.readouterr().out
        assert code == 0
        assert "0 short form(s) in entries before 2026-11-24 not checked" in out

    def test_the_count_is_printed_when_it_is_not_zero(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _entry(repo, "2026-01-01-1-old.md", anchor="`impl.Thing`", applies_to="none (p)")

        code = _main(repo, "check", "--resolve", "--project-root", repo.as_posix())

        assert code == 0
        assert "1 short form(s) in entries before 2026-11-24 not checked" in capsys.readouterr().out

    def test_a_stale_reference_fails_the_command(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _entry(repo, "2026-01-01-1-stale.md", anchor="`pkg.impl.Gone`", applies_to="none (p)")

        code = _main(repo, "check", "--resolve", "--project-root", repo.as_posix())

        assert code == 1
        assert "`pkg.impl.Gone` doesn't resolve" in capsys.readouterr().err

    def test_without_resolve_references_are_not_checked(self, repo: Path) -> None:
        """The format check (pre-commit) stays fast: no resolving without --resolve."""
        _entry(repo, "2026-01-01-1-stale.md", anchor="`pkg.impl.Gone`", applies_to="none (p)")

        assert _main(repo, "check") == 0

    def test_resolve_without_pyeye_fails_never_passes(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _entry(repo, "2026-01-01-1-ok.md", anchor="`pkg.impl.Thing`", applies_to="none (p)")
        real = importlib.import_module

        def no_pyeye(name: str, *args: object) -> object:
            if name == "pyeye.decision_check":
                raise ImportError("no pyeye here")
            return real(name, *args)  # type: ignore[arg-type]

        monkeypatch.setattr(importlib, "import_module", no_pyeye)

        code = _main(repo, "check", "--resolve", "--project-root", repo.as_posix())

        assert code == 1
        assert "--resolve needs pyeye" in capsys.readouterr().err


class TestThisRepo:
    def test_the_wrapper_gates_short_forms_from_the_landing_day(self) -> None:
        wrapper_path = Path(__file__).resolve().parents[1] / "scripts" / "decisions.py"
        spec = importlib.util.spec_from_file_location("decisions_wrapper_gate", wrapper_path)
        assert spec is not None and spec.loader is not None
        wrapper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wrapper)

        assert wrapper.SHORT_FORMS_FAIL_FROM == GATE
