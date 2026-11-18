"""The GitHub issue forms ask for what triage needs (#70).

Each form under ``.github/ISSUE_TEMPLATE`` must parse, label itself with a label
the project defines (``docs/LABELS.md``), and keep its field ids unique. The bug
form must keep asking for the facts a pyeye bug can't be reproduced without.
``config.yml`` turns off blank issues and links to pages that exist.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / ".github" / "ISSUE_TEMPLATE"
FORMS = sorted(p for p in TEMPLATES.glob("*.yml") if p.name != "config.yml")
_REPO_BLOB = "https://github.com/okeefeco/pyeye-mcp/blob/main/"


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), path.name
    return data


def _defined_labels() -> set[str]:
    text = (ROOT / "docs" / "LABELS.md").read_text(encoding="utf-8")
    return set(re.findall(r"^- `([^`]+)`", text, re.MULTILINE))


def _fields(form: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in form["body"] if "id" in item}


def test_the_expected_forms_exist() -> None:
    assert {p.stem for p in FORMS} == {
        "bug_report",
        "feature_request",
        "documentation",
        "question",
    }


@pytest.mark.parametrize("path", FORMS, ids=lambda p: p.stem)
def test_a_form_is_well_formed(path: Path) -> None:
    form = _load(path)

    assert form["name"] and form["description"]
    assert form["labels"] and set(form["labels"]) <= _defined_labels(), form["labels"]
    ids = [item["id"] for item in form["body"] if "id" in item]
    assert len(ids) == len(set(ids)), f"duplicate field ids in {path.name}"
    for item in form["body"]:
        assert item["type"] in {"markdown", "input", "textarea", "dropdown", "checkboxes"}
        if item["type"] == "dropdown":
            assert item["attributes"]["options"], item["id"]


def _required(form: dict[str, Any]) -> set[str]:
    return {
        fid
        for fid, item in _fields(form).items()
        if (item.get("validations") or {}).get("required")
    }


def test_the_bug_form_asks_for_what_triage_needs() -> None:
    form = _load(TEMPLATES / "bug_report.yml")
    fields = _fields(form)

    assert form["labels"] == ["bug"]
    assert {"version", "tool-call", "actual", "expected", "platform", "python"} <= _required(form)
    assert "pyeye://about" in fields["version"]["attributes"]["description"]
    # Config bugs are common, so the config has its own (optional) field.
    assert "config" in fields and "config" not in _required(form)
    assert {"Linux", "macOS", "Windows"} <= set(fields["platform"]["attributes"]["options"])


def test_config_turns_off_blank_issues_and_links_pages_that_exist() -> None:
    config = _load(TEMPLATES / "config.yml")

    assert config["blank_issues_enabled"] is False
    links = config["contact_links"]
    assert {link["name"] for link in links} >= {"Report a security vulnerability"}
    for link in links:
        assert link["url"].startswith(_REPO_BLOB), link["url"]
        assert (ROOT / link["url"].removeprefix(_REPO_BLOB)).is_file(), link["url"]


@pytest.mark.parametrize("path", [*FORMS, TEMPLATES / "config.yml"], ids=lambda p: p.stem)
def test_repo_links_in_a_form_point_at_files_that_exist(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for url in re.findall(re.escape(_REPO_BLOB) + r"[^\s)\"']+", text):
        target = url.removeprefix(_REPO_BLOB).split("#", 1)[0]
        assert (ROOT / target).is_file(), url
