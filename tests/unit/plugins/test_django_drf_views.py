"""``find_django_views`` reports Django REST framework views too (#947).

Every record carries ``framework``: ``"django"`` or ``"rest_framework"``, always
present. A DRF class view has a base the module imports from ``rest_framework``
whose name contains ``View`` (``APIView``, ``generics.ListAPIView``,
``viewsets.ModelViewSet``); a DRF function view is decorated with
``rest_framework``'s ``@api_view``. The same precision rule as Django's (#941):
a base or decorator counts only through the module's own imports.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from pyeye import project_manager as project_manager_module
from pyeye.plugins.django import DjangoPlugin
from pyeye.project_manager import ProjectManager


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


async def _views(root: Path) -> list[tuple[str, str, str]]:
    found = await DjangoPlugin(root).find_views()
    return sorted((v["name"], v["type"], v["framework"]) for v in found)


@pytest.fixture
def app(tmp_path: Path) -> Path:
    _write(tmp_path, "api/__init__.py", "")
    return tmp_path


@pytest.fixture
def isolated_manager(monkeypatch: pytest.MonkeyPatch) -> Iterator[ProjectManager]:
    manager = ProjectManager(max_projects=10)
    monkeypatch.setattr(project_manager_module, "_project_manager", manager)
    yield manager
    manager.cleanup_all()


DRF = "rest_framework"


class TestClassViews:
    @pytest.mark.asyncio
    async def test_apiview_generics_and_viewsets(self, app: Path) -> None:
        _write(
            app,
            "api/views.py",
            "from rest_framework.views import APIView\n"
            "from rest_framework import generics, mixins, viewsets\n"
            "import rest_framework.viewsets as vs\n\n"
            "class Plain(APIView):\n    pass\n\n"
            "class Listing(generics.ListAPIView):\n    pass\n\n"
            "class Models(viewsets.ModelViewSet):\n    pass\n\n"
            "class Mixed(mixins.ListModelMixin, viewsets.GenericViewSet):\n    pass\n\n"
            "class Aliased(vs.ReadOnlyModelViewSet):\n    pass\n",
        )

        assert await _views(app) == [
            ("Aliased", "class_view", DRF),
            ("Listing", "class_view", DRF),
            ("Mixed", "class_view", DRF),
            ("Models", "class_view", DRF),
            ("Plain", "class_view", DRF),
        ]

    @pytest.mark.asyncio
    async def test_negatives(self, app: Path) -> None:
        _write(
            app,
            "api/views.py",
            "from rest_framework import mixins\n"
            "from myapp.rest_framework import APIView as Shadow\n"
            "from .base import ViewSet\n\n"
            "class APIView:\n    pass\n\n"
            "class Local(APIView):\n    pass\n\n"
            "class Nested(Shadow):\n    pass\n\n"
            "class Project(ViewSet):\n    pass\n\n"
            "class MixinOnly(mixins.ListModelMixin):\n    pass\n",
        )

        assert await _views(app) == []

    @pytest.mark.asyncio
    async def test_a_drf_base_wins_over_a_django_one(self, app: Path) -> None:
        _write(
            app,
            "api/views.py",
            "from django.views import View\n"
            "from rest_framework.views import APIView\n\n"
            "class Both(View, APIView):\n    pass\n\n"
            "class JustDjango(View):\n    pass\n",
        )

        assert await _views(app) == [
            ("Both", "class_view", DRF),
            ("JustDjango", "class_view", "django"),
        ]


class TestFunctionViews:
    @pytest.mark.asyncio
    async def test_api_view_in_every_spelling(self, app: Path) -> None:
        _write(
            app,
            "api/views.py",
            "from rest_framework.decorators import api_view\n"
            "from rest_framework.decorators import api_view as endpoint\n"
            "from rest_framework import decorators\n\n"
            "@api_view(['GET'])\n"
            "def called(request):\n    return None\n\n"
            "@api_view\n"
            "def bare(req):\n    return None\n\n"
            "@endpoint(['POST'])\n"
            "async def aliased(r):\n    return None\n\n"
            "@decorators.api_view(['GET'])\n"
            "def dotted(request):\n    return None\n\n"
            "def plain(request):\n    return None\n",
        )

        assert await _views(app) == [
            ("aliased", "function_view", DRF),
            ("bare", "function_view", DRF),
            ("called", "function_view", DRF),
            ("dotted", "function_view", DRF),
            ("plain", "function_view", "django"),
        ]

    @pytest.mark.asyncio
    async def test_another_api_view_decorator_doesnt_count(self, app: Path) -> None:
        _write(
            app,
            "api/views.py",
            "from rest_framework import status\n"
            "from .decorators import api_view\n\n"
            "@api_view(['GET'])\n"
            "def lookalike(r):\n    return None\n\n"
            "@status.api_view\n"
            "def wrong_module(r):\n    return None\n",
        )

        assert await _views(app) == []

    @pytest.mark.asyncio
    async def test_a_star_import_of_the_decorators(self, app: Path) -> None:
        _write(
            app,
            "api/views.py",
            "from rest_framework.decorators import *\n\n"
            "@api_view(['GET'])\n"
            "def starred(r):\n    return None\n",
        )

        assert await _views(app) == [("starred", "function_view", DRF)]


class TestFiles:
    @pytest.mark.asyncio
    async def test_viewsets_and_api_modules_and_packages(self, app: Path) -> None:
        drf_class = "from rest_framework import viewsets\n\nclass {}(viewsets.ViewSet):\n    pass\n"
        _write(app, "api/viewsets.py", drf_class.format("InViewsets"))
        _write(app, "shop/__init__.py", "")
        _write(app, "shop/api.py", drf_class.format("InApi"))
        _write(app, "shop/viewsets/__init__.py", "")
        _write(app, "shop/viewsets/users.py", drf_class.format("InViewsetsPackage"))
        _write(app, "api/users.py", drf_class.format("InApiPackage"))
        _write(app, "shop/serializers.py", drf_class.format("NotScanned"))

        assert [name for name, _, _ in await _views(app)] == [
            "InApi",
            "InApiPackage",
            "InViewsets",
            "InViewsetsPackage",
        ]

    @pytest.mark.asyncio
    async def test_an_api_module_without_framework_imports_contributes_nothing(
        self, app: Path
    ) -> None:
        """A generic api.py name is safe: the file must import django or rest_framework."""
        _write(app, "shop/__init__.py", "")
        _write(
            app,
            "shop/api.py",
            "import requests\nfrom .client import ApiView\n\n"
            "class Client(ApiView):\n    pass\n\n"
            "class Wrapper(View):\n    pass\n\n"
            "def fetch(request):\n    return requests.get(request)\n",
        )

        assert await _views(app) == []

    @pytest.mark.asyncio
    async def test_a_drf_only_views_file_is_read(self, app: Path) -> None:
        """#941's gate needed a django import; a DRF-only views.py was skipped."""
        _write(
            app,
            "api/views.py",
            "from rest_framework.views import APIView\n\n"
            "class Only(APIView):\n    pass\n\n"
            "def helper(request):\n    return None\n",
        )

        assert await _views(app) == [
            ("Only", "class_view", DRF),
            ("helper", "function_view", "django"),
        ]


@pytest.mark.usefixtures("isolated_manager")
class TestSubclasses:
    @pytest.mark.asyncio
    async def test_a_subclass_inherits_the_seeds_framework(self, app: Path) -> None:
        _write(
            app,
            "api/views.py",
            "from rest_framework import viewsets\n"
            "from django.views.generic import ListView\n\n"
            "class ApiBase(viewsets.ModelViewSet):\n    pass\n\n"
            "class PageBase(ListView):\n    pass\n",
        )
        _write(
            app,
            "api/extra.py",
            "from api.views import ApiBase, PageBase\n\n"
            "class Users(ApiBase):\n    pass\n\n"
            "class Pages(PageBase):\n    pass\n\n"
            "class Deeper(Users):\n    pass\n",
        )

        assert await _views(app) == [
            ("ApiBase", "class_view", DRF),
            ("Deeper", "class_view", DRF),
            ("PageBase", "class_view", "django"),
            ("Pages", "class_view", "django"),
            ("Users", "class_view", DRF),
        ]

    @pytest.mark.asyncio
    async def test_rest_framework_wins_down_the_tree(self, app: Path) -> None:
        """A class under both a Django and a DRF seed is DRF, and so are its subclasses."""
        _write(
            app,
            "api/views.py",
            "from rest_framework.views import APIView\n"
            "from django.views import View\n\n"
            "class ApiBase(APIView):\n    pass\n\n"
            "class Both(View):\n    pass\n",
        )
        _write(
            app,
            "api/more.py",
            "from api.views import ApiBase, Both\n\n"
            "class Joined(Both, ApiBase):\n    pass\n\n"
            "class Below(Joined):\n    pass\n",
        )

        assert await _views(app) == [
            ("ApiBase", "class_view", DRF),
            ("Below", "class_view", DRF),
            ("Both", "class_view", "django"),
            ("Joined", "class_view", DRF),
        ]

    @pytest.mark.asyncio
    async def test_a_direct_django_view_under_a_drf_seed_is_raised(self, app: Path) -> None:
        _write(
            app,
            "api/views.py",
            "from rest_framework.views import APIView\n"
            "from django.views import View\n\n"
            "class ApiBase(APIView):\n    pass\n\n"
            "class Direct(View, ApiBase):\n    pass\n",
        )

        assert await _views(app) == [
            ("ApiBase", "class_view", DRF),
            ("Direct", "class_view", DRF),
        ]


@pytest.mark.asyncio
async def test_every_record_carries_framework(app: Path) -> None:
    _write(
        app,
        "api/views.py",
        "from django.views.generic import ListView\n\n"
        "class Page(ListView):\n    pass\n\n"
        "def index(request):\n    return None\n",
    )

    for record in await DjangoPlugin(app).find_views():
        assert record["framework"] in {"django", "rest_framework"}
