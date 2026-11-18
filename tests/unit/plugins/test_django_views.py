"""``find_django_views`` finds the views a Django app defines (#941).

Class views: a class with a base whose name contains ``View`` and that the
module imports from Django (``ListView``, ``generic.ListView``,
``django.views.View``). Function views: a ``def`` or ``async def`` whose first
parameter is ``request``. Files: each ``views.py`` and every module of a
``views`` package, when the file imports Django in any form.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.plugins.django import DjangoPlugin


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


async def _views(root: Path) -> list[tuple[str, str]]:
    return sorted((v["name"], v["type"]) for v in await DjangoPlugin(root).find_views())


@pytest.fixture
def app(tmp_path: Path) -> Path:
    _write(tmp_path, "shop/__init__.py", "")
    return tmp_path


class TestClassViews:
    @pytest.mark.asyncio
    async def test_attribute_and_name_bases(self, app: Path) -> None:
        _write(
            app,
            "shop/views.py",
            "import django.views\n"
            "from django.views import generic\n"
            "from django.views.generic import ListView as LV\n\n"
            "class AttrList(generic.ListView):\n    pass\n\n"
            "class Aliased(LV):\n    pass\n\n"
            "class Dotted(django.views.View):\n    pass\n",
        )

        assert await _views(app) == [
            ("Aliased", "class_view"),
            ("AttrList", "class_view"),
            ("Dotted", "class_view"),
        ]

    @pytest.mark.asyncio
    async def test_one_record_per_class(self, app: Path) -> None:
        """Two Django view bases used to give two records (#941)."""
        _write(
            app,
            "shop/views.py",
            "from django.views.generic import RedirectView, View\n\n"
            "class Both(RedirectView, View):\n    pass\n",
        )

        assert await _views(app) == [("Both", "class_view")]

    @pytest.mark.asyncio
    async def test_a_base_not_from_django_is_not_a_view(self, app: Path) -> None:
        _write(
            app,
            "shop/views.py",
            "from django.http import HttpResponse\n"
            "from rest_framework.views import APIView\n"
            "from .helpers import ViewHelper\n"
            "from django import forms\n\n"
            "class LocalView:\n    pass\n\n"
            "class A(ViewHelper):\n    pass\n\n"
            "class B(LocalView):\n    pass\n\n"
            "class C(APIView):\n    pass\n\n"
            "class D(forms.Form):\n    pass\n",
        )

        assert await _views(app) == []

    @pytest.mark.asyncio
    async def test_a_star_import_from_django_counts_unbound_names_only(self, app: Path) -> None:
        _write(
            app,
            "shop/views.py",
            "from django.views.generic import *\n\n"
            "class ViewMixin:\n    pass\n\n"
            "class Starred(TemplateView):\n    pass\n\n"
            "class Local(ViewMixin):\n    pass\n",
        )

        assert await _views(app) == [("Starred", "class_view")]

    @pytest.mark.asyncio
    async def test_a_subclass_of_a_project_view_is_not_followed_yet(self, app: Path) -> None:
        """Following project subclasses is #942."""
        _write(
            app,
            "shop/views.py",
            "from django.views.generic import ListView\n\n"
            "class Base(ListView):\n    pass\n\n"
            "class Indirect(Base):\n    pass\n",
        )

        assert await _views(app) == [("Base", "class_view")]


class TestFunctionViews:
    @pytest.mark.asyncio
    async def test_sync_and_async(self, app: Path) -> None:
        _write(
            app,
            "shop/views.py",
            "from django.http import HttpResponse\n\n"
            "def plain(request):\n    return HttpResponse()\n\n"
            "async def later(request, pk):\n    return HttpResponse()\n\n"
            "def helper(req):\n    return req\n",
        )

        assert await _views(app) == [("later", "function_view"), ("plain", "function_view")]


class TestFiles:
    @pytest.mark.asyncio
    async def test_a_views_package(self, app: Path) -> None:
        _write(app, "shop/views/__init__.py", "from .posts import PostDetail\n")
        _write(
            app,
            "shop/views/posts.py",
            "from django.views.generic import DetailView\n\n"
            "class PostDetail(DetailView):\n    pass\n",
        )
        _write(app, "shop/views/admin/__init__.py", "")
        _write(
            app,
            "shop/views/admin/tools.py",
            "from django.http import HttpResponse\n\n"
            "def tool(request):\n    return HttpResponse()\n",
        )

        assert await _views(app) == [("PostDetail", "class_view"), ("tool", "function_view")]

    @pytest.mark.asyncio
    async def test_a_views_directory_that_is_not_a_package_is_not_scanned(self, app: Path) -> None:
        _write(
            app,
            "docs/views/example.py",
            "from django.http import HttpResponse\n\n"
            "def sample(request):\n    return HttpResponse()\n",
        )

        assert await _views(app) == []

    @pytest.mark.asyncio
    async def test_other_modules_are_not_scanned(self, app: Path) -> None:
        _write(
            app,
            "shop/handlers.py",
            "from django.views.generic import ListView\n\n" "class NotHere(ListView):\n    pass\n",
        )

        assert await _views(app) == []

    @pytest.mark.asyncio
    async def test_an_import_django_file_is_read(self, app: Path) -> None:
        """The gate used to be the text "from django" (#941)."""
        _write(
            app,
            "shop/views.py",
            "import django.views.generic as g\n\n"
            "class Page(g.TemplateView):\n    pass\n\n"
            "def index(request):\n    return None\n",
        )

        assert await _views(app) == [("Page", "class_view"), ("index", "function_view")]

    @pytest.mark.asyncio
    async def test_a_file_without_django_imports_is_skipped(self, app: Path) -> None:
        _write(
            app,
            "shop/views.py",
            "# from django this is not\nfrom .models import thing\n\n"
            "def index(request):\n    return thing\n",
        )

        assert await _views(app) == []
