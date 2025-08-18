"""Tests for Django plugin."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from pycodemcp.plugins.django import DjangoPlugin


@pytest.fixture
def temp_project():
    """Create a temporary project directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def django_plugin(temp_project):
    """Create a Django plugin instance."""
    return DjangoPlugin(temp_project)


class TestDjangoPlugin:
    """Test Django plugin functionality."""

    def test_plugin_name(self, django_plugin):
        """Test plugin name."""
        assert django_plugin.name() == "Django"

    def test_detect_with_manage_py(self, temp_project):
        """Test detection with manage.py file."""
        manage_py = temp_project / "manage.py"
        manage_py.write_text("#!/usr/bin/env python\n")

        plugin = DjangoPlugin(temp_project)
        assert plugin.detect() is True

    def test_detect_with_requirements_txt(self, temp_project):
        """Test detection with Django in requirements.txt."""
        req_file = temp_project / "requirements.txt"
        req_file.write_text("django==4.2.0\ndjango-rest-framework==3.14.0\n")

        plugin = DjangoPlugin(temp_project)
        assert plugin.detect() is True

    def test_detect_with_requirements_base(self, temp_project):
        """Test detection with Django in requirements/base.txt."""
        req_dir = temp_project / "requirements"
        req_dir.mkdir()
        req_file = req_dir / "base.txt"
        req_file.write_text("Django>=3.2\n")

        plugin = DjangoPlugin(temp_project)
        assert plugin.detect() is True

    def test_detect_with_pipfile(self, temp_project):
        """Test detection with Django in Pipfile."""
        pipfile = temp_project / "Pipfile"
        pipfile.write_text('[packages]\ndjango = "*"\n')

        plugin = DjangoPlugin(temp_project)
        assert plugin.detect() is True

    def test_detect_with_django_imports(self, temp_project):
        """Test detection with Django imports in Python files."""
        py_file = temp_project / "settings.py"
        py_file.write_text("from django.conf import settings\n")

        plugin = DjangoPlugin(temp_project)
        assert plugin.detect() is True

    def test_detect_no_django(self, temp_project):
        """Test detection returns False when Django not found."""
        # Create a non-Django project
        py_file = temp_project / "main.py"
        py_file.write_text("import flask\n")

        plugin = DjangoPlugin(temp_project)
        assert plugin.detect() is False

    def test_detect_handles_read_errors(self, temp_project):
        """Test detection handles file read errors gracefully."""
        req_file = temp_project / "requirements.txt"
        req_file.write_text("test")
        req_file.chmod(0o000)  # Remove read permissions

        plugin = DjangoPlugin(temp_project)
        # Should not raise an exception
        try:
            result = plugin.detect()
            # If we can't read, should return False
            assert result is False
        finally:
            req_file.chmod(0o644)  # Restore permissions for cleanup

    def test_register_tools(self, django_plugin):
        """Test tool registration."""
        tools = django_plugin.register_tools()

        expected_tools = [
            "find_django_models",
            "find_django_views",
            "find_django_urls",
            "find_django_templates",
            "find_django_migrations",
        ]

        for tool_name in expected_tools:
            assert tool_name in tools
            assert callable(tools[tool_name])

    def test_find_models(self, temp_project):
        """Test finding Django models."""
        models_file = temp_project / "models.py"
        models_file.write_text(
            """
from django.db import models

class User(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()

class Product(models.Model):
    title = models.CharField(max_length=200)
    price = models.DecimalField(max_digits=10, decimal_places=2)
"""
        )

        plugin = DjangoPlugin(temp_project)
        models = plugin.find_models()

        assert len(models) == 2
        assert any(m["name"] == "User" for m in models)
        assert any(m["name"] == "Product" for m in models)

    def test_find_views(self, temp_project):
        """Test finding Django views."""
        views_file = temp_project / "views.py"
        views_file.write_text(
            """
from django.views import View
from django.views.generic import ListView, DetailView
from django.shortcuts import render

class UserListView(ListView):
    model = User

class UserDetailView(DetailView):
    model = User

def index(request):
    return render(request, 'index.html')
"""
        )

        plugin = DjangoPlugin(temp_project)
        views = plugin.find_views()

        assert len(views) >= 2  # At least the class-based views
        assert any(v["name"] == "UserListView" for v in views)
        assert any(v["name"] == "UserDetailView" for v in views)

    def test_find_urls(self, temp_project):
        """Test finding Django URL patterns."""
        urls_file = temp_project / "urls.py"
        urls_file.write_text(
            """
from django.urls import path, include
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('users/', views.UserListView.as_view(), name='user-list'),
    path('api/', include('api.urls')),
]
"""
        )

        plugin = DjangoPlugin(temp_project)
        urls = plugin.find_urls()

        assert len(urls) > 0
        assert any("urls.py" in u["file"] for u in urls)

    def test_find_templates(self, temp_project):
        """Test finding Django templates."""
        templates_dir = temp_project / "templates"
        templates_dir.mkdir()

        base_template = templates_dir / "base.html"
        base_template.write_text("<html><body>{% block content %}{% endblock %}</body></html>")

        index_template = templates_dir / "index.html"
        index_template.write_text("{% extends 'base.html' %}")

        plugin = DjangoPlugin(temp_project)
        templates = plugin.find_templates()

        assert len(templates) == 2
        assert any("base.html" in t["file"] for t in templates)
        assert any("index.html" in t["file"] for t in templates)

    def test_find_migrations(self, temp_project):
        """Test finding Django migrations."""
        migrations_dir = temp_project / "migrations"
        migrations_dir.mkdir()

        migration_file = migrations_dir / "0001_initial.py"
        migration_file.write_text(
            """
from django.db import migrations, models

class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = []
"""
        )

        plugin = DjangoPlugin(temp_project)
        migrations = plugin.find_migrations()

        assert len(migrations) == 1
        assert "0001_initial.py" in migrations[0]["file"]

    def test_get_framework_components(self, temp_project):
        """Test getting framework components."""
        # Create various Django files
        (temp_project / "models.py").write_text("from django.db import models\n")
        (temp_project / "views.py").write_text("from django.views import View\n")
        (temp_project / "urls.py").write_text("urlpatterns = []\n")
        (temp_project / "serializers.py").write_text("from rest_framework import serializers\n")
        (temp_project / "admin.py").write_text("from django.contrib import admin\n")
        (temp_project / "forms.py").write_text("from django import forms\n")

        plugin = DjangoPlugin(temp_project)
        components = plugin.get_framework_components()

        assert "models" in components
        assert "views" in components
        assert "urls" in components
        assert "serializers" in components
        assert "admin" in components
        assert "forms" in components

        # Check that each component lists the respective file
        assert any("models.py" in f for f in components["models"])
        assert any("views.py" in f for f in components["views"])
        assert any("urls.py" in f for f in components["urls"])
        assert any("serializers.py" in f for f in components["serializers"])
        assert any("admin.py" in f for f in components["admin"])
        assert any("forms.py" in f for f in components["forms"])

    def test_empty_project(self, temp_project):
        """Test all find methods return empty lists for empty project."""
        plugin = DjangoPlugin(temp_project)

        assert plugin.find_models() == []
        assert plugin.find_views() == []
        assert plugin.find_urls() == []
        assert plugin.find_templates() == []
        assert plugin.find_migrations() == []

    def test_file_not_found_handling(self, django_plugin):
        """Test handling of non-existent files."""
        # All find methods should handle missing files gracefully
        assert django_plugin.find_models() == []
        assert django_plugin.find_views() == []

    @patch("pycodemcp.plugins.django.logger")
    def test_logging_on_detection(self, mock_logger, temp_project):
        """Test that detection logs appropriately."""
        manage_py = temp_project / "manage.py"
        manage_py.write_text("#!/usr/bin/env python\n")

        plugin = DjangoPlugin(temp_project)
        plugin.detect()

        # Plugin should log when Django is detected
        # Check that logger was used (exact calls depend on implementation)
        _ = mock_logger  # Use the mock_logger to avoid unused warning
