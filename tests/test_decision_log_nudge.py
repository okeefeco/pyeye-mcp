"""Tests for the decision-log post-commit nudge's contract-surface detector.

Drives the tightened net: dunder/constructor signatures and output-shape
dict-key additions must be caught; private helpers, tests/docs, and trivial
body edits must stay silent (a nudge you learn to ignore is worse than none).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "decision_log_nudge.py"
_spec = importlib.util.spec_from_file_location("decision_log_nudge", _SCRIPT)
assert _spec and _spec.loader
nudge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nudge)


def _diff(path: str, body: str) -> str:
    """Wrap hunk *body* in a minimal git-show diff for *path*."""
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n{body}"


def test_public_signature_change_detected():
    body = "@@ -1,1 +1,1 @@\n-def resolve(handle):\n+def resolve(handle, scope):\n"
    found = nudge.scan(_diff("src/pyeye/x.py", body))
    assert "resolve" in found["public signature"]


def test_constructor_dunder_signature_detected():
    """Changing __init__ is a public constructor contract — must be caught."""
    body = (
        "@@ -1,1 +1,1 @@\n-    def __init__(self, cap=500):\n+    def __init__(self, cap=None):\n"
    )
    found = nudge.scan(_diff("src/pyeye/cache.py", body))
    assert "__init__" in found["public signature"]


def test_private_helper_signature_ignored():
    body = "@@ -1,1 +1,1 @@\n-def _helper(a):\n+def _helper(a, b):\n"
    found = nudge.scan(_diff("src/pyeye/x.py", body))
    assert "public signature" not in found


def test_env_key_detected():
    body = '@@ -1,0 +1,1 @@\n+    self.x = self._get_int_env("PYEYE_NEW_KNOB", 5)\n'
    found = nudge.scan(_diff("src/pyeye/settings.py", body))
    assert "PYEYE_NEW_KNOB" in found["config/env key"]


def test_output_shape_dict_key_in_report_detected():
    """Adding a key to a *report* function's return dict is an output contract."""
    body = (
        "@@ -1,3 +1,4 @@ def get_performance_report(self) -> dict:\n"
        "         return {\n"
        '             "cache": self.cache_metrics.get_stats(),\n'
        '+            "artifact_cache": file_artifact_cache.stats(),\n'
        "         }\n"
    )
    found = nudge.scan(_diff("src/pyeye/metrics.py", body))
    assert "artifact_cache" in found["output-shape key"]


def test_dict_key_in_non_output_function_ignored():
    body = (
        "@@ -1,2 +1,3 @@ def _build_internal(self):\n"
        "         d = {\n"
        '+            "scratch": 1,\n'
        "         }\n"
    )
    found = nudge.scan(_diff("src/pyeye/x.py", body))
    assert "output-shape key" not in found


def test_tests_and_docs_paths_ignored():
    body = "@@ -1,1 +1,1 @@\n-def public_thing():\n+def public_thing(x):\n"
    assert nudge.scan(_diff("tests/test_x.py", body)) == {}
    assert nudge.scan(_diff("docs/guide.md", body)) == {}


def test_non_shipped_paths_ignored():
    """Only the shipped surface (src/) is a contract surface — dev tooling isn't.

    Guards against the nudge firing on its own kind of change (scripts/, ci, etc.).
    """
    body = "@@ -1,0 +1,1 @@\n+def scan(diff):\n"
    assert nudge.scan(_diff("scripts/decision_log_nudge.py", body)) == {}
    assert nudge.scan(_diff("noxfile.py", body)) == {}


def test_trivial_body_change_silent():
    body = "@@ -1,1 +1,1 @@ def existing(self):\n-    return 1\n+    return 2\n"
    assert nudge.scan(_diff("src/pyeye/x.py", body)) == {}
