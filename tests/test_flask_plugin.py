"""Tests for Flask plugin."""

import tempfile
from pathlib import Path

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


def test_find_routes():
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
        routes = plugin.find_routes()

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


def test_find_blueprints():
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
        blueprints = plugin.find_blueprints()

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


def test_find_error_handlers():
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
        handlers = plugin.find_error_handlers()

        assert len(handlers) == 3

        # Check 404 handler
        handler_404 = next((h for h in handlers if h["error_code"] == 404), None)
        assert handler_404 is not None
        assert handler_404["name"] == "not_found"

        # Check Exception handler
        exception_handler = next((h for h in handlers if h["error_code"] == "Exception"), None)
        assert exception_handler is not None


def test_find_extensions():
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
        extensions = plugin.find_extensions()

        # Check that we found the extensions
        ext_names = [e["extension"] for e in extensions]
        assert "flask_sqlalchemy" in ext_names
        assert "flask_login" in ext_names
        assert "flask_cors" in ext_names


def test_find_cli_commands():
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
        commands = plugin.find_cli_commands()

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
