---
date: 2026-11-20
command: resolve and inspect, in process, on scenario django (pyeye-scenarios skill) at its pinned cd385e6b8c, project_path <TARGET>/django
commit: 4f6ee1d3
machine: not recorded (Python 3.12, MemoryMax=2G)
---

# `django` star re-export probes

A dated record of the probes added by #1007 (PR #1012), captured on build
`2.2.1.dev4+g4f6ee1d38` (the #1007 branch @ `4f6ee1d3`). It sits beside
[`django.md`](django.md), which stays unedited; record a new baseline as a new
record.

`django/forms/__init__.py` re-exports through `from django.forms.forms import *`
and similar lines, and each source module's `__all__` lists the name.
Before #1007 every probe here was `found: false`.

| # | Probe | Expected (baseline) | Demonstrates / tracking |
|---|-------|---------------------|-------------------------|
| 1 | `resolve("django.forms.Form")` | `handle: django.forms.forms.Form`, `kind:class`, `scope:project`, `forms/forms.py:432` | **star re-export**: followed to the definition site (#1007) |
| 2 | `resolve("django.forms.CharField")` | `django.forms.fields.CharField`, `class`, `project`, `forms/fields.py:276` | the same, through another star source |
| 3 | `resolve("django.forms.ModelForm")` | `django.forms.models.ModelForm`, `class`, `project`, `forms/models.py:585` | the same |
| 4 | `resolve("django.forms.Widget")` | `django.forms.widgets.Widget`, `class`, `project`, `forms/widgets.py:320` | the same |
| 5 | `inspect("django.forms.Form")` | `handle: django.forms.forms.Form`; `re_exports: []` | `re_exports` doesn't list the star alias yet: **#1010**. When it does, this row changes. |

Any of rows 1–4 coming back `found: false` is a regression of #1007.
