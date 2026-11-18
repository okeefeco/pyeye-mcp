---
date: "2026-11-18"
title: "find_django_views: a class view's base must be imported from Django; views packages and async views count (#941)"
issues: [941, 942, 873]
anchors: ["pyeye.plugins.django.DjangoPlugin.find_views", "pyeye.plugins.django._is_django_view_base", "pyeye.plugins.django._django_bindings", "pyeye.plugins.django._in_views_package", "tests/unit/plugins/test_django_views.py"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-19-942-find-django-views-follows-project-subclasses.md"]
superseded_by: []
---

## 2026-11-18 — find_django_views: a class view's base must be imported from Django; views packages and async views count (#941)

**Friction:** `find_django_views` was both narrower and broader than `docs/api/django-tools.md` ("class-based views and function views"), found by the docs review.

- **Narrower:** it missed attribute bases (`generic.ListView`), which `find_models` in the same plugin handles. It also missed `async def` views, `views/` packages, and files that import Django without the text "from django".
- **Broader:** any bare base whose name contained `View` counted, Django or not. A class with two such bases was reported twice.

**Decision:**

- **Files:** every `views.py`, plus every module of a package named `views` (walking up through package directories only). The file must import Django in some form; the text gate is gone.
- **Class views:** the class has a base whose name contains `View` and whose root name the module imports from Django. That covers `from django.views.generic import ListView` (aliases are followed), `from django.views import generic` → `generic.ListView`, and `import django.views` → `django.views.View`. Under a `from django… import *`, a bare name the module binds no other way also counts. One record per class.
- **Function views:** `def` or `async def` whose first parameter is `request`, as before plus async (the #873 Flask fix).
- **Deliberately not counted:**
  - a base from another framework (Django REST framework's `APIView`), because it isn't imported from Django;
  - a project class whose name contains `View`.

  That narrowing is the point: membership is decided by the file's imports, not by the name. Counting DRF would need its own rule.
- **Not yet:** a subclass of a project view (`class Indirect(Base)`, where `Base(ListView)`). That needs the class graph (`subclasses`) and is #942.

**Anchor:** `pyeye.plugins.django.DjangoPlugin.find_views`, `_is_django_view_base`, `_django_bindings`, `_in_views_package`; `tests/unit/plugins/test_django_views.py`; #941.

**Applies-to:**

- `pyeye.plugins.django.DjangoPlugin.find_views` and its helpers `_views_files`, `_in_views_package`, `_django_bindings`, `_base_parts`, `_is_django_view_base` and `_view_record`.
- `docs/api/django-tools.md` (find_django_views).

**Verify:** gold — `uv run pytest tests/unit/plugins/test_django_views.py` passes. It checks:

- attribute, aliased and dotted bases;
- one record for a class with two view bases;
- non-Django bases (a project `ViewHelper`, a local class, DRF `APIView`, `forms.Form`) don't count;
- the star-import rule;
- a project subclass isn't followed (#942);
- sync and async function views;
- `views` packages are scanned, and a plain `views` directory and other modules aren't;
- `import django…` files are read, and a file without Django imports is skipped.
