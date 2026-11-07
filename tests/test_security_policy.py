"""SECURITY.md stays reachable and its supported-versions table stays current (#69)."""

from __future__ import annotations

import re
from pathlib import Path

import scripts.changelog as cl

_ROOT = Path(__file__).resolve().parents[1]
_POLICY = (_ROOT / "SECURITY.md").read_text(encoding="utf-8")


def test_reports_go_to_private_vulnerability_reporting():
    assert "https://github.com/okeefeco/pyeye-mcp/security/advisories/new" in _POLICY
    assert "do not report security vulnerabilities in public issues" in _POLICY


def test_readme_links_the_policy():
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert "(SECURITY.md)" in readme


def test_current_major_is_listed_as_supported():
    """After the next major release, this fails until the table is updated."""
    latest = cl.latest_version(cl.parse(cl.CHANGELOG.read_text(encoding="utf-8")))
    assert latest is not None
    major = latest.split(".")[0]
    row = re.search(rf"^\| {major}\.x\s*\|(?P<cell>[^|]*)\|", _POLICY, re.MULTILINE)
    assert row, f"SECURITY.md has no '| {major}.x |' row for the current major ({latest})"
    assert "Yes" in row["cell"], f"{major}.x is the current major but isn't marked supported"
