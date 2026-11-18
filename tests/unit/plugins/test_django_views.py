"""``find_django_views`` finds the views a Django app defines (#941).

Class views: a class with a base whose name contains ``View`` and that the
module imports from Django (``ListView``, ``generic.ListView``,
``django.views.View``), and the project classes that subclass one (#942). Function views: a ``def`` or ``async def`` whose first
parameter is ``request``. Files: each ``views.py`` and every module of a
``views`` package, when the file imports Django in any form.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from pyeye import project_manager as project_manager_module
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.plugins.django import DjangoPlugin, _in_views_package
from pyeye.project_manager import ProjectManager
from tests.utils.performance import PerformanceThresholds, assert_performance_threshold


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
    async def test_a_base_not_from_a_framework_is_not_a_view(self, app: Path) -> None:
        """Only an imported framework base counts; DRF's own APIView does since #947."""
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

        assert await _views(app) == [("C", "class_view")]

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
    async def test_a_star_import_rebound_by_an_assignment_doesnt_count(self, app: Path) -> None:
        """A module-level assignment binds the name locally, so the star didn't."""
        _write(
            app,
            "shop/views.py",
            "from django.views.generic import *\n"
            "import mylib\n"
            "from .base import Local\n\n"
            "TemplateView = Local\n"
            "RedirectView: type = Local\n"
            "(DetailView, other) = (Local, Local)\n\n"
            "class Rebound(TemplateView):\n    pass\n\n"
            "class Annotated(RedirectView):\n    pass\n\n"
            "class Unpacked(DetailView):\n    pass\n\n"
            "class Attr(mylib.ListView):\n    pass\n\n"
            "class Kept(ListView):\n    pass\n",
        )

        assert await _views(app) == [("Kept", "class_view")]

    @pytest.mark.asyncio
    async def test_a_call_or_subscript_base_is_not_traced(self, app: Path) -> None:
        """``make_view()`` or ``bases[0]`` can't be traced to an import; another base still counts."""
        _write(
            app,
            "shop/views.py",
            "from django.views.generic import ListView\n"
            "from .factories import make_view, bases\n\n"
            "class Called(make_view()):\n    pass\n\n"
            "class Indexed(bases[0]):\n    pass\n\n"
            "class Mixed(make_view(), ListView):\n    pass\n",
        )

        assert await _views(app) == [("Mixed", "class_view")]


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


@pytest.fixture
def isolated_manager(monkeypatch: pytest.MonkeyPatch) -> Iterator[ProjectManager]:
    manager = ProjectManager(max_projects=10)
    monkeypatch.setattr(project_manager_module, "_project_manager", manager)
    yield manager
    manager.cleanup_all()


@pytest.mark.usefixtures("isolated_manager")
class TestSubclassesOfViews:
    """Project classes that subclass a class view are views too (#942)."""

    @pytest.mark.asyncio
    async def test_subclasses_are_followed_at_any_depth_and_in_any_module(self, app: Path) -> None:
        _write(
            app,
            "shop/views.py",
            "from django.views.generic import ListView\n\n"
            "class Base(ListView):\n    pass\n\n"
            "class Indirect(Base):\n    pass\n",
        )
        _write(
            app,
            "shop/mixins.py",
            "from shop.views import Indirect\n\n"
            "class Deeper(Indirect):\n    pass\n\n"
            "class NotAView:\n    pass\n",
        )

        views = await DjangoPlugin(app).find_views()

        assert [(v["name"], v["type"]) for v in views] == [
            ("Base", "class_view"),
            ("Deeper", "class_view"),
            ("Indirect", "class_view"),
        ]
        deeper = next(v for v in views if v["name"] == "Deeper")
        assert deeper["file"].endswith("shop/mixins.py") and deeper["line"] == 3

    @pytest.mark.asyncio
    async def test_a_class_found_both_ways_is_reported_once(self, app: Path) -> None:
        _write(
            app,
            "shop/views.py",
            "from django.views.generic import ListView, View\n\n"
            "class Base(ListView):\n    pass\n\n"
            "class Both(Base, View):\n    pass\n",
        )

        assert await _views(app) == [("Base", "class_view"), ("Both", "class_view")]

    @pytest.mark.asyncio
    async def test_no_class_views_means_no_class_graph(
        self, app: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A project without Django class views never pays for the graph build."""
        _write(
            app,
            "shop/views.py",
            "from django.http import HttpResponse\n\n"
            "def index(request):\n    return HttpResponse()\n",
        )

        async def fail(*_args: object, **_kwargs: object) -> dict[str, object]:
            raise AssertionError("find_subclasses called without a class view")

        monkeypatch.setattr(JediAnalyzer, "find_subclasses", fail)

        assert await _views(app) == [("index", "function_view")]

    @pytest.mark.asyncio
    async def test_a_cycle_terminates(self, app: Path) -> None:
        """A bad hierarchy (a project class graph with a cycle) doesn't loop."""
        _write(
            app,
            "shop/views.py",
            "from django.views.generic import ListView\n\n"
            "class Base(ListView):\n    pass\n\n"
            "class A(Base, C):\n    pass\n\n"
            "class C(A):\n    pass\n",
        )

        assert await _views(app) == [
            ("A", "class_view"),
            ("Base", "class_view"),
            ("C", "class_view"),
        ]


#: A cold find_django_views on a mid-size project: it builds the shared class
#: graph over every file in scope (#942). 150 modules and 1,500 classes, each
#: module subclassing classes it imports from the one before, so every base
#: goes through the class graph's base resolution. Under 1 s locally (2026-11-18).
FIND_VIEWS_COLD = PerformanceThresholds(
    base=6000.0, linux_ci=8000.0, macos_ci=12000.0, windows_ci=12000.0
)


@pytest.mark.usefixtures("isolated_manager")
@pytest.mark.asyncio
async def test_cold_cost_on_a_mid_size_project(app: Path) -> None:
    _write(app, "shop/models_0.py", "".join(f"class Thing0_{j}:\n    pass\n\n" for j in range(10)))
    for i in range(1, 150):
        _write(
            app,
            f"shop/models_{i}.py",
            f"from shop.models_{i - 1} import Thing{i - 1}_0 as Parent\n"
            f"from shop import models_{i - 1} as previous\n\n"
            + "".join(
                f"class Thing{i}_{j}({'Parent' if j % 2 else f'previous.Thing{i - 1}_{j}'}):\n"
                "    pass\n\n"
                for j in range(10)
            ),
        )
    _write(
        app,
        "shop/views.py",
        "from django.views.generic import ListView\n\n"
        "class Base(ListView):\n    pass\n\n"
        + "".join(f"class Page{j}(Base):\n    pass\n\n" for j in range(20)),
    )

    start = time.perf_counter()
    views = await DjangoPlugin(app).find_views()
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert len(views) == 21
    assert_performance_threshold(
        elapsed_ms, FIND_VIEWS_COLD, "Cold find_django_views (150 modules)"
    )


class TestDefensiveBranches:
    @pytest.mark.asyncio
    async def test_an_unreadable_views_file_is_skipped(
        self, app: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(
            app,
            "shop/views.py",
            "from django.http import HttpResponse\n\ndef a(request):\n    pass\n",
        )
        _write(app, "blog/__init__.py", "")
        _write(
            app,
            "blog/views.py",
            "from django.http import HttpResponse\n\ndef b(request):\n    pass\n",
        )
        plugin = DjangoPlugin(app)
        real = plugin._read_source

        async def unreadable_shop(path: Path) -> str | None:
            return None if path.parent.name == "shop" else await real(path)

        monkeypatch.setattr(plugin, "_read_source", unreadable_shop)

        assert [v["name"] for v in await plugin.find_views()] == ["b"]

    @pytest.mark.asyncio
    async def test_an_unparseable_views_file_is_skipped(self, app: Path) -> None:
        """Broken user code is skipped with a warning (#622), and the rest still counts."""
        _write(app, "shop/views.py", "from django.http import HttpResponse\n\ndef broken(:\n")
        _write(app, "blog/__init__.py", "")
        _write(
            app,
            "blog/views.py",
            "from django.http import HttpResponse\n\ndef ok(request):\n    pass\n",
        )

        assert await _views(app) == [("ok", "function_view")]

    def test_the_package_walk_stops_at_the_filesystem_root(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every directory up to the root looks like a package: the walk still ends."""
        monkeypatch.setattr(Path, "is_file", lambda self: self.name == "__init__.py")

        assert _in_views_package(Path("/a/b/mod.py")) is False
        assert _in_views_package(Path("/a/views/b/mod.py")) is True


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
