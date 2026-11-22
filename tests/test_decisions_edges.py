"""``pyeye.decisions``' validation and ``migrate`` edge paths, in process (#1100).

The engine moved from ``scripts/`` (never coverage-measured) into the package
in #1093, and these paths were untested before the move too. No behaviour
changes here: each test pins what the module already does.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye import decisions


def _meta(**overrides: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "date": "2026-01-02",
        "title": "A decision (#1)",
        "issues": [1],
        "anchors": ["pkg.f"],
        "status": "active",
        "amends": [],
        "supersedes": [],
        "amended_by": [],
        "superseded_by": [],
    }
    meta.update(overrides)
    return meta


def _body(date: str = "2026-01-02", title: str = "A decision (#1)") -> str:
    return f"## {date} — {title}\n\n**Applies-to:** `pkg.f`\n"


def _write(directory: Path, name: str, meta: dict[str, Any], body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(decisions.render(meta, body), encoding="utf-8", newline="\n")


def _problems(directory: Path) -> list[str]:
    entries, errors = decisions.load(directory)
    return errors + decisions.check(entries)


class TestCheckMessages:
    NAME = "2026-01-02-1-a-decision.md"

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"date": 20260102}, "date must be a 'YYYY-MM-DD' string"),
            ({"title": ""}, "title must be a non-empty string"),
            ({"anchors": "pkg.f"}, "anchors must be a list of non-empty strings"),
            ({"amends": "x.md"}, "amends must be a list of entry file names"),
        ],
    )
    def test_a_malformed_field_is_named(
        self, tmp_path: Path, overrides: dict[str, Any], message: str
    ) -> None:
        _write(tmp_path, self.NAME, _meta(**overrides), _body())

        assert any(message in p for p in _problems(tmp_path)), _problems(tmp_path)

    def test_a_body_without_the_heading_is_named(self, tmp_path: Path) -> None:
        _write(tmp_path, self.NAME, _meta(), "no heading\n\n**Applies-to:** `pkg.f`\n")

        assert any("body must start with '## YYYY-MM-DD" in p for p in _problems(tmp_path))

    def test_a_reverse_link_to_a_missing_entry_is_named(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            self.NAME,
            _meta(status="amended", amended_by=["2026-02-01-2-gone.md"]),
            _body(),
        )

        assert any("which doesn't exist" in p for p in _problems(tmp_path))

    def test_a_one_sided_reverse_link_is_named(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            self.NAME,
            _meta(status="amended", amended_by=["2026-02-01-2-new.md"]),
            _body(),
        )
        _write(
            tmp_path,
            "2026-02-01-2-new.md",
            _meta(date="2026-02-01", title="New (#2)", issues=[2]),
            _body("2026-02-01", "New (#2)"),
        )

        assert any("doesn't list" in p for p in _problems(tmp_path)), _problems(tmp_path)


class TestDefaults:
    def test_load_reads_docs_decisions_entries_under_the_working_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path / "docs" / "decisions" / "entries", "2026-01-02-1-a.md", _meta(), _body())
        monkeypatch.chdir(tmp_path)

        entries, errors = decisions.load()

        assert [e.name for e in entries] == ["2026-01-02-1-a.md"] and not errors

    def test_migrate_uses_the_same_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        log = tmp_path / "docs" / "decisions" / "DECISIONS.md"
        log.parent.mkdir(parents=True)
        log.write_text(decisions.STATIC_HEADER + "\n" + _body(), encoding="utf-8", newline="\n")
        monkeypatch.chdir(tmp_path)

        notes = decisions.migrate()

        assert any(n.startswith("created: ") for n in notes)
        assert (tmp_path / "docs" / "decisions" / "entries").is_dir()


class TestMigrateGuards:
    def test_an_unreadable_entry_stops_it(self, tmp_path: Path) -> None:
        entries = tmp_path / "entries"
        entries.mkdir()
        (entries / "2026-01-02-1-broken.md").write_text("no front matter\n", encoding="utf-8")
        log = tmp_path / "DECISIONS.md"
        log.write_text(decisions.STATIC_HEADER, encoding="utf-8", newline="\n")

        with pytest.raises(decisions.EntryError):
            decisions.migrate(log, entries)

    def test_a_name_collision_stops_it(self, tmp_path: Path) -> None:
        """Two log entries whose names come out the same: nothing is written."""
        log = tmp_path / "DECISIONS.md"
        log.write_text(
            decisions.STATIC_HEADER
            + "\n"
            + _body(title="Same title (#1)")
            + "\n"
            + _body(title="Same title (#1) ")
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

        with pytest.raises(decisions.EntryError, match="name collision"):
            decisions.migrate(log, tmp_path / "entries")
        assert not (tmp_path / "entries").exists() or not list((tmp_path / "entries").iterdir())

    @pytest.mark.parametrize("update", [False, True])
    def test_a_lossy_write_is_caught_on_the_round_trip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, update: bool
    ) -> None:
        """The guard that verifies each written body; a lossy render trips it."""
        entries = tmp_path / "entries"
        log = tmp_path / "DECISIONS.md"
        if update:  # an existing entry whose body the log has changed
            _write(entries, "2026-01-02-1-a-decision.md", _meta(), _body())
        log.write_text(
            decisions.STATIC_HEADER + "\n" + _body() + "\nmore\n", encoding="utf-8", newline="\n"
        )
        real = decisions.render
        monkeypatch.setattr(decisions, "render", lambda meta, body: real(meta, body[:-5]))

        with pytest.raises(decisions.EntryError, match="body changed on the round trip"):
            decisions.migrate(log, entries, update=update)

    def test_a_long_title_gives_a_bounded_slug(self) -> None:
        slug = decisions._slug("word " * 40 + "(#1)")

        assert len(slug) <= 60 and slug.startswith("word-word")


class TestMain:
    def test_migrate_prints_its_notes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log = tmp_path / "DECISIONS.md"
        log.write_text(decisions.STATIC_HEADER + "\n" + _body(), encoding="utf-8", newline="\n")
        code = decisions.main(["--dir", str(tmp_path / "entries"), "--log", str(log), "migrate"])

        assert code == 0
        assert "created: " in capsys.readouterr().out

    @pytest.mark.parametrize("command", ["index", "check"])
    def test_no_entries_in_process(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
    ) -> None:
        code = decisions.main(["--decisions-dir", str(tmp_path / "missing"), command])

        out = capsys.readouterr().out
        assert code == 0
        assert "no entries" in out and "does not exist" in out

    def test_index_warns_about_an_unreadable_entry(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, "2026-01-02-1-a.md", _meta(), _body())
        (tmp_path / "2026-01-03-1-broken.md").write_text("no front matter\n", encoding="utf-8")

        assert decisions.main(["--dir", str(tmp_path), "index"]) == 0
        captured = capsys.readouterr()
        assert "warning:" in captured.err and "2026-01-02-1-a.md" in captured.out
