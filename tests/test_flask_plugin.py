"""Tests for Flask plugin."""

import tempfile
from pathlib import Path

import pytest

from src.pycodemcp.plugins.flask import FlaskPlugin


def test_flask_detection():
    """Test Flask project detection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a simple Flask app
        app_py = Path(tmpdir) / "app.py"
        app_py.write_text(
            """
from flask import Flask, render_template, request

app = Flask(__name__)

@app.route('/')
def home():
    return 'Hello World'

@app.route('/users/<int:user_id>')
def get_user(user_id):
    return f'User {user_id}'

if __name__ == '__main__':
    app.run()
"""
        )

        plugin = FlaskPlugin(tmpdir)
        assert plugin.detect() is True
        assert plugin.name() == "Flask"


@pytest.mark.asyncio
async def test_find_routes():
    """Test finding Flask routes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create Flask app with routes
        app_py = Path(tmpdir) / "app.py"
        app_py.write_text(
            """
from flask import Flask

app = Flask(__name__)

@app.route('/')
def index():
    return 'Home'

@app.route('/api/users', methods=['GET', 'POST'])
def users():
    return 'Users'

@app.route('/api/users/<int:user_id>', methods=['GET', 'PUT', 'DELETE'])
def user_detail(user_id):
    return f'User {user_id}'
"""
        )

        plugin = FlaskPlugin(tmpdir)
        routes = await plugin.find_routes()

        assert len(routes) == 3

        # Check first route
        index_route = next((r for r in routes if r["name"] == "index"), None)
        assert index_route is not None
        assert index_route["path"] == "/"
        assert index_route["methods"] == ["GET"]

        # Check users route
        users_route = next((r for r in routes if r["name"] == "users"), None)
        assert users_route is not None
        assert users_route["path"] == "/api/users"
        assert set(users_route["methods"]) == {"GET", "POST"}


@pytest.mark.asyncio
async def test_find_blueprints():
    """Test finding Flask blueprints."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create blueprint file
        auth_py = Path(tmpdir) / "auth.py"
        auth_py.write_text(
            """
from flask import Blueprint

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/login')
def login():
    return 'Login'

api_bp = Blueprint('api', __name__, url_prefix='/api/v1')
"""
        )

        plugin = FlaskPlugin(tmpdir)
        blueprints = await plugin.find_blueprints()

        assert len(blueprints) == 2

        # Check auth blueprint
        auth_bp = next((b for b in blueprints if b["name"] == "auth_bp"), None)
        assert auth_bp is not None
        assert auth_bp["blueprint_name"] == "auth"
        assert auth_bp["url_prefix"] == "/auth"

        # Check api blueprint
        api_bp = next((b for b in blueprints if b["name"] == "api_bp"), None)
        assert api_bp is not None
        assert api_bp["blueprint_name"] == "api"
        assert api_bp["url_prefix"] == "/api/v1"


@pytest.mark.asyncio
async def test_find_error_handlers():
    """Test finding error handlers."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create app with error handlers
        app_py = Path(tmpdir) / "app.py"
        app_py.write_text(
            """
from flask import Flask

app = Flask(__name__)

@app.errorhandler(404)
def not_found(error):
    return 'Not Found', 404

@app.errorhandler(500)
def internal_error(error):
    return 'Internal Server Error', 500

@app.errorhandler(Exception)
def handle_exception(error):
    return 'Something went wrong', 500
"""
        )

        plugin = FlaskPlugin(tmpdir)
        handlers = await plugin.find_error_handlers()

        assert len(handlers) == 3

        # Check 404 handler
        handler_404 = next((h for h in handlers if h["error_code"] == 404), None)
        assert handler_404 is not None
        assert handler_404["name"] == "not_found"

        # Check Exception handler
        exception_handler = next((h for h in handlers if h["error_code"] == "Exception"), None)
        assert exception_handler is not None


@pytest.mark.asyncio
async def test_find_extensions():
    """Test finding Flask extensions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create app with extensions
        app_py = Path(tmpdir) / "app.py"
        app_py.write_text(
            """
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_cors import CORS

app = Flask(__name__)
db = SQLAlchemy(app)
login_manager = LoginManager(app)
CORS(app)
"""
        )

        plugin = FlaskPlugin(tmpdir)
        extensions = await plugin.find_extensions()

        # Check that we found the extensions
        ext_names = [e["extension"] for e in extensions]
        assert "flask_sqlalchemy" in ext_names
        assert "flask_login" in ext_names
        assert "flask_cors" in ext_names


@pytest.mark.asyncio
async def test_find_cli_commands():
    """Test finding CLI commands."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create app with CLI commands
        app_py = Path(tmpdir) / "app.py"
        app_py.write_text(
            """
from flask import Flask
import click

app = Flask(__name__)

@app.cli.command()
def init_db():
    '''Initialize the database.'''
    pass

@app.cli.command('seed')
def seed_data():
    '''Seed test data.'''
    pass
"""
        )

        plugin = FlaskPlugin(tmpdir)
        commands = await plugin.find_cli_commands()

        assert len(commands) == 2

        # Check init_db command
        init_cmd = next((c for c in commands if c["function"] == "init_db"), None)
        assert init_cmd is not None

        # Check seed command with custom name
        seed_cmd = next((c for c in commands if c["name"] == "seed"), None)
        assert seed_cmd is not None
        assert seed_cmd["function"] == "seed_data"


def test_no_flask_detection():
    """Test that non-Flask projects are not detected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a non-Flask Python file
        main_py = Path(tmpdir) / "main.py"
        main_py.write_text(
            """
def main():
    print("Hello World")

if __name__ == "__main__":
    main()
"""
        )

        plugin = FlaskPlugin(tmpdir)
        assert plugin.detect() is False


def test_flask_detection_requirements():
    """Test Flask detection via requirements files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Test with requirements.txt
        req_file = Path(tmpdir) / "requirements.txt"
        req_file.write_text("flask==2.3.0\nrequests==2.31.0")

        plugin = FlaskPlugin(tmpdir)
        assert plugin.detect() is True


def test_flask_detection_pyproject():
    """Test Flask detection via pyproject.toml."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Test with pyproject.toml
        pyproject = Path(tmpdir) / "pyproject.toml"
        pyproject.write_text(
            """
[tool.poetry.dependencies]
python = "^3.8"
flask = "^2.3.0"
"""
        )

        plugin = FlaskPlugin(tmpdir)
        assert plugin.detect() is True


def test_flask_detection_pipfile():
    """Test Flask detection via Pipfile."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Test with Pipfile
        pipfile = Path(tmpdir) / "Pipfile"
        pipfile.write_text(
            """
[packages]
flask = "*"
sqlalchemy = "*"
"""
        )

        plugin = FlaskPlugin(tmpdir)
        assert plugin.detect() is True


def test_flask_detection_requirements_base():
    """Test Flask detection via requirements/base.txt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create requirements directory
        req_dir = Path(tmpdir) / "requirements"
        req_dir.mkdir()
        req_file = req_dir / "base.txt"
        req_file.write_text("Flask>=2.0.0")

        plugin = FlaskPlugin(tmpdir)
        assert plugin.detect() is True


def test_flask_detection_exceptions():
    """Test Flask detection with file read errors."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a file that will cause read error
        app_py = Path(tmpdir) / "app.py"
        app_py.write_text("from flask import Flask")
        app_py.chmod(0o000)  # Remove read permissions

        # Create a readable requirements file with flask
        req_file = Path(tmpdir) / "requirements.txt"
        req_file.write_text("flask")

        plugin = FlaskPlugin(tmpdir)
        # Should still detect Flask from requirements
        assert plugin.detect() is True

        # Restore permissions for cleanup
        app_py.chmod(0o644)


@pytest.mark.asyncio
async def test_find_views_method_view():
    """Test finding MethodView classes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        views_py = Path(tmpdir) / "views.py"
        views_py.write_text(
            """
from flask import Flask
from flask.views import MethodView

class UserAPI(MethodView):
    def get(self, user_id):
        if user_id is None:
            return 'list users'
        else:
            return f'get user {user_id}'

    def post(self):
        return 'create user'

class ItemAPI(MethodView):
    def get(self):
        return 'list items'
"""
        )

        plugin = FlaskPlugin(tmpdir)
        views = await plugin.find_views()

        assert len(views) == 2
        view_names = [v["name"] for v in views]
        assert "UserAPI" in view_names
        assert "ItemAPI" in view_names
        assert all(v["type"] == "method_view" for v in views)


@pytest.mark.asyncio
async def test_find_templates():
    """Test finding templates and render_template calls."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create templates directory
        templates_dir = Path(tmpdir) / "templates"
        templates_dir.mkdir()

        # Create HTML templates
        (templates_dir / "index.html").write_text("<h1>Home</h1>")
        (templates_dir / "user.html").write_text("<h1>User</h1>")

        # Create Jinja2 template
        (templates_dir / "base.jinja2").write_text("<!DOCTYPE html>")

        # Create nested template
        admin_dir = templates_dir / "admin"
        admin_dir.mkdir()
        (admin_dir / "dashboard.html").write_text("<h1>Admin</h1>")

        # Create app with render_template calls
        app_py = Path(tmpdir) / "app.py"
        app_py.write_text(
            """
from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/user')
def user():
    return render_template('user.html', name='John')

@app.route('/admin')
def admin():
    return render_template('admin/dashboard.html')
"""
        )

        plugin = FlaskPlugin(tmpdir)
        result = await plugin.find_templates()

        assert len(result) == 1
        templates_data = result[0]

        # Check templates
        templates = templates_data["templates"]
        assert len(templates) == 4
        template_names = [t["name"] for t in templates]
        assert "index.html" in template_names
        assert "user.html" in template_names
        assert "base.jinja2" in template_names
        assert "admin/dashboard.html" in template_names

        # Check render_template calls
        render_calls = templates_data["render_calls"]
        assert len(render_calls) == 3
        rendered_templates = [r["template"] for r in render_calls]
        assert "index.html" in rendered_templates
        assert "user.html" in rendered_templates
        assert "admin/dashboard.html" in rendered_templates


@pytest.mark.asyncio
async def test_find_config():
    """Test finding Flask configuration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create config.py
        config_py = Path(tmpdir) / "config.py"
        config_py.write_text(
            """
class Config:
    SECRET_KEY = 'dev'  # pragma: allowlist secret
    DATABASE_URI = 'sqlite:///app.db'
"""
        )

        # Create settings.py
        settings_py = Path(tmpdir) / "settings.py"
        settings_py.write_text(
            """
DEBUG = True
TESTING = False
"""
        )

        # Create nested config
        config_dir = Path(tmpdir) / "app"
        config_dir.mkdir()
        (config_dir / "config.py").write_text("# App config")

        # Create app with config usage
        app_py = Path(tmpdir) / "app.py"
        app_py.write_text(
            """
from flask import Flask, current_app

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret'  # pragma: allowlist secret
app.config.from_object('config.Config')

@app.route('/debug')
def debug():
    return str(app.config['DEBUG'])

@app.route('/settings')
def settings():
    return str(current_app.config.get('TESTING'))
"""
        )

        plugin = FlaskPlugin(tmpdir)
        configs = await plugin.find_config()

        # Check config files
        config_files = [c for c in configs if c["type"] == "config_file"]
        assert len(config_files) >= 2
        config_paths = [c["file"] for c in config_files]
        assert any("config.py" in p for p in config_paths)
        assert any("settings.py" in p for p in config_paths)

        # Check config access
        config_access = [c for c in configs if c["type"] == "config_access"]
        assert len(config_access) > 0


@pytest.mark.asyncio
async def test_find_extensions_import_variations():
    """Test finding Flask extensions with different import styles."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create app with various import styles
        app_py = Path(tmpdir) / "app.py"
        app_py.write_text(
            """
import flask_migrate
from flask_wtf import FlaskForm
from flask_marshmallow import Marshmallow
import flask_jwt_extended as jwt

app = Flask(__name__)
migrate = flask_migrate.Migrate(app)
ma = Marshmallow(app)
"""
        )

        plugin = FlaskPlugin(tmpdir)
        extensions = await plugin.find_extensions()

        ext_names = [e["extension"] for e in extensions]
        assert "flask_migrate" in ext_names
        assert "flask_wtf" in ext_names
        assert "flask_marshmallow" in ext_names
        assert "flask_jwt_extended" in ext_names


@pytest.mark.asyncio
async def test_find_cli_commands_click_decorator():
    """Test finding CLI commands with click decorators."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app_py = Path(tmpdir) / "cli.py"
        app_py.write_text(
            """
from flask import Flask
import click

app = Flask(__name__)

@click.command
def custom_command():
    '''Custom command without parentheses.'''
    pass

@app.cli.command()
def another_command():
    '''Another CLI command.'''
    pass
"""
        )

        plugin = FlaskPlugin(tmpdir)
        commands = await plugin.find_cli_commands()

        # The current implementation only finds @app.cli.command decorators
        # @click.command without the app.cli prefix is not detected
        assert len(commands) == 1
        assert commands[0]["name"] == "another_command"


def test_get_framework_components():
    """Test getting framework components."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create route files
        routes_py = Path(tmpdir) / "routes.py"
        routes_py.write_text(
            """
@app.route('/')
def home():
    return 'Home'
"""
        )

        # Create blueprint file
        auth_py = Path(tmpdir) / "auth.py"
        auth_py.write_text("from flask import Blueprint")

        # Create templates directory
        templates_dir = Path(tmpdir) / "templates"
        templates_dir.mkdir()

        # Create static directory
        static_dir = Path(tmpdir) / "static"
        static_dir.mkdir()

        # Create models.py
        models_py = Path(tmpdir) / "models.py"
        models_py.write_text("# Database models")

        # Create forms.py
        forms_py = Path(tmpdir) / "forms.py"
        forms_py.write_text("# WTForms")

        plugin = FlaskPlugin(tmpdir)
        components = plugin.get_framework_components()

        assert "routes" in components
        assert "blueprints" in components
        assert "templates" in components
        assert "static" in components
        assert "models" in components
        assert "forms" in components

        assert len(components["routes"]) == 1
        assert len(components["blueprints"]) == 1
        assert len(components["templates"]) == 1
        assert len(components["static"]) == 1
        assert len(components["models"]) == 1
        assert len(components["forms"]) == 1


@pytest.mark.asyncio
async def test_edge_cases_malformed_code():
    """Test handling of malformed code and edge cases."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create file with syntax error
        bad_py = Path(tmpdir) / "bad.py"
        bad_py.write_text(
            """
from flask import Flask
@app.route('/test'
def test():  # Missing closing parenthesis
    return 'test'
"""
        )

        # Create file with partial Flask code
        partial_py = Path(tmpdir) / "partial.py"
        partial_py.write_text(
            """
# This might be Flask but not valid
@route('/test')
def test():
    pass
"""
        )

        plugin = FlaskPlugin(tmpdir)

        # Should not crash on malformed code
        routes = await plugin.find_routes()
        assert isinstance(routes, list)

        blueprints = await plugin.find_blueprints()
        assert isinstance(blueprints, list)

        views = await plugin.find_views()
        assert isinstance(views, list)


@pytest.mark.asyncio
async def test_error_handler_with_num_decorator():
    """Test finding error handlers with ast.Num (older Python compatibility)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app_py = Path(tmpdir) / "errors.py"
        app_py.write_text(
            """
from flask import Flask

app = Flask(__name__)

@app.errorhandler(403)
def forbidden(e):
    return 'Forbidden', 403

@app.errorhandler(ValueError)
def handle_value_error(e):
    return 'Invalid value', 400
"""
        )

        plugin = FlaskPlugin(tmpdir)
        handlers = await plugin.find_error_handlers()

        # Should find both handlers
        assert len(handlers) >= 2
        error_codes = [h.get("error_code") for h in handlers]
        assert 403 in error_codes
        assert "ValueError" in error_codes
