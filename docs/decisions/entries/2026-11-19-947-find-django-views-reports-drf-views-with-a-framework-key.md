---
date: "2026-11-19"
title: "find_django_views reports Django REST framework views; every record carries framework (#947)"
issues: [947, 941, 942]
anchors: ["pyeye.plugins.django.DjangoPlugin.find_views", "pyeye.plugins.django._Bindings", "pyeye.plugins.django._bindings", "pyeye.plugins.django._class_view_framework", "pyeye.plugins.django._is_api_view", "tests/unit/plugins/test_django_drf_views.py"]
status: "active"
amends: ["2026-11-18-941-a-django-view-base-must-come-from-django.md", "2026-11-19-942-find-django-views-follows-project-subclasses.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-19 — find_django_views reports Django REST framework views; every record carries framework (#947)

**Friction:** #941's import rule dropped DRF views, which the old name-only check had counted by accident (`APIView`, `ModelViewSet`). A DRF-only views file imports no `django`, so it was skipped entirely.

**Decision:**

- **Record shape:** `type` is unchanged (`class_view`, `function_view`). A DRF view IS a Django view, so a consumer filtering on `type` still sees it. Every record gains `framework`: `"django"` or `"rest_framework"`. It's always present, never conditional.
- **Rejected shapes:**
  - new `type` values (`drf_view`, `viewset`), because they hide DRF views from `type: class_view` filters;
  - no marker, because DRF and plain Django views would be indistinguishable.
- **Detection,** with the #941 precision rule applied per package (`_bindings(tree, package)`, top level only, no relative imports):
  - **Class:** a base imported from `rest_framework` whose imported name contains `View`. That covers `APIView`, `generics.ListAPIView`, the `viewsets` classes, aliases and star imports. A `rest_framework` base wins over a Django one.
  - **Not counted:** mixins alone, project classes named `APIView` or `ViewSet`, and `myapp.rest_framework`.
  - **Function:** a decorator, called or not, that names exactly `rest_framework.decorators.api_view`, by its full dotted import path. Another `api_view`, including one reached through another `rest_framework` module, doesn't count. A `request`-first function without it stays a `django` function view.
- **Inheritance (#942):** a subclass inherits its seed's framework, and `rest_framework` wins. A class under both a Django and a DRF seed is DRF, the upgrade propagates to its subclasses, and a direct Django view under a DRF seed is raised to DRF.
- **Files:** `views`, `viewsets` and `api`, both as modules (`views.py`, `viewsets.py`, `api.py`) and as packages. A file must import `django` or `rest_framework`.
  - A generic `api.py` is safe: an unrelated one has no framework imports, and every base is import-checked anyway.
- It's an `added` change (a new key), so it ships in v2.2.0.

**Anchor:** `pyeye.plugins.django.DjangoPlugin.find_views`, `_Bindings`, `_bindings`, `_class_view_framework`, `_is_api_view`; `tests/unit/plugins/test_django_drf_views.py`; #947.

**Applies-to:**

- `pyeye.plugins.django.DjangoPlugin.find_views` and its helpers (`_views_files`, `_indirect_class_views`, `_in_views_package`, `_Bindings`, `_bindings`, `_is_view_base`, `_class_view_framework`, `_is_api_view`, `_view_record`).
- `docs/api/django-tools.md` (find_django_views, including its example output).

**Verify:** gold — `uv run pytest tests/unit/plugins/test_django_drf_views.py tests/unit/plugins/test_django_views.py` passes. It checks:

- the DRF class and function forms, and their negatives;
- a DRF base wins over a Django one;
- the new file names and packages, an `api.py` with no framework imports, and a DRF-only views file;
- framework inheritance and the upgrade;
- every record has `framework`.
