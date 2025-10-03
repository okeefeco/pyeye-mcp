"""Shared fixtures and test utilities for Python Code Intelligence MCP tests."""

import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import jedi
import pytest


@pytest.fixture
def temp_project_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test projects."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_python_project(temp_project_dir: Path) -> Path:
    """Create a sample Python project structure."""
    # Create main module
    main_py = temp_project_dir / "main.py"
    main_py.write_text(
        """
import utils
from models import User

def main():
    user = User("test")
    return utils.process(user)

if __name__ == "__main__":
    main()
"""
    )

    # Create utils module
    utils_py = temp_project_dir / "utils.py"
    utils_py.write_text(
        """
def process(data):
    \"\"\"Process the input data.\"\"\"
    return str(data)

def helper(x: int) -> int:
    \"\"\"Helper function with type hints.\"\"\"
    return x * 2
"""
    )

    # Create models module
    models_py = temp_project_dir / "models.py"
    models_py.write_text(
        """
class User:
    \"\"\"User model class.\"\"\"

    def __init__(self, name: str):
        self.name = name

    def __str__(self) -> str:
        return f"User({self.name})"

class Admin(User):
    \"\"\"Admin user with extra privileges.\"\"\"

    def __init__(self, name: str, level: int = 1):
        super().__init__(name)
        self.level = level
"""
    )

    # Create nested package
    package_dir = temp_project_dir / "mypackage"
    package_dir.mkdir()

    init_py = package_dir / "__init__.py"
    init_py.write_text('__version__ = "0.1.0"')

    module_py = package_dir / "module.py"
    module_py.write_text(
        """
def package_function():
    \"\"\"Function inside a package.\"\"\"
    return "package"
"""
    )

    return temp_project_dir


@pytest.fixture
def namespace_package_dirs(temp_project_dir: Path) -> dict[str, list[Path]]:
    """Create a distributed namespace package structure."""
    # Create company-auth repo
    auth_dir = temp_project_dir / "company-auth"
    auth_dir.mkdir()
    auth_pkg = auth_dir / "company" / "auth"
    auth_pkg.mkdir(parents=True)

    (auth_pkg / "__init__.py").write_text("")
    (auth_pkg / "models.py").write_text(
        """
class AuthUser:
    def __init__(self, username: str):
        self.username = username
"""
    )

    # Create company-api repo
    api_dir = temp_project_dir / "company-api"
    api_dir.mkdir()
    api_pkg = api_dir / "company" / "api"
    api_pkg.mkdir(parents=True)

    (api_pkg / "__init__.py").write_text("")
    (api_pkg / "client.py").write_text(
        """
from company.auth.models import AuthUser

class APIClient:
    def __init__(self, user: AuthUser):
        self.user = user
"""
    )

    return {"company": [auth_dir, api_dir]}


@pytest.fixture
def mock_jedi_project() -> Mock:
    """Create a mock Jedi project."""
    project = Mock(spec=jedi.Project)
    project.path = Path("/test/project")

    # Mock search results
    mock_name = Mock()
    mock_name.name = "test_function"
    mock_name.module_name = "test_module"
    mock_name.line = 10
    mock_name.column = 4
    mock_name.module_path = Path("/test/project/test_module.py")
    mock_name.type = "function"
    mock_name.docstring = Mock(return_value="Test function docstring")
    mock_name.is_definition = Mock(return_value=True)

    project.search = Mock(return_value=[mock_name])

    return project


@pytest.fixture
def mock_jedi_script() -> Mock:
    """Create a mock Jedi script."""
    script = Mock(spec=jedi.Script)

    # Mock goto result
    mock_definition = Mock()
    mock_definition.name = "test_definition"
    mock_definition.module_name = "test_module"
    mock_definition.line = 5
    mock_definition.column = 0
    mock_definition.module_path = Path("/test/project/test_module.py")
    mock_definition.type = "class"
    mock_definition.docstring = Mock(return_value="Test class docstring")

    script.goto = Mock(return_value=[mock_definition])
    script.get_references = Mock(return_value=[])
    script.infer = Mock(return_value=[])

    return script


@pytest.fixture
def mock_watchdog_observer() -> Mock:
    """Create a mock watchdog observer."""
    observer = Mock()
    observer.start = Mock()
    observer.stop = Mock()
    observer.join = Mock()
    observer.schedule = Mock()
    observer.is_alive = Mock(return_value=True)

    return observer


@pytest.fixture
def sample_config_json(temp_project_dir: Path) -> Path:
    """Create a sample .pycodemcp.json config file."""
    config_file = temp_project_dir / ".pycodemcp.json"
    config_file.write_text(
        """{
    "packages": ["../lib1", "../lib2"],
    "namespaces": {
        "company": ["~/repos/company-auth", "~/repos/company-api"]
    },
    "cache_ttl": 600,
    "max_projects": 5
}"""
    )
    return config_file


@pytest.fixture
def sample_pyproject_toml(temp_project_dir: Path) -> Path:
    """Create a sample pyproject.toml with pycodemcp config."""
    config_file = temp_project_dir / "pyproject.toml"
    config_file.write_text(
        """
[tool.pycodemcp]
packages = ["../shared", "../common"]
cache_ttl = 300

[tool.pycodemcp.namespaces]
mycompany = ["/repos/mycompany-core", "/repos/mycompany-utils"]
"""
    )
    return config_file


@pytest.fixture
def mock_mcp_server() -> Mock:
    """Create a mock MCP server instance."""
    server = Mock()
    server.tool = Mock()
    server.run = Mock()

    # Mock tool decorator
    def tool_decorator(*args: Any, **kwargs: Any) -> Any:  # noqa: ARG001
        def decorator(func: Any) -> Any:
            return func

        return decorator

    server.tool = tool_decorator

    return server


@pytest.fixture
def sample_flask_project(temp_project_dir: Path) -> Path:
    """Create a sample Flask project."""
    app_py = temp_project_dir / "app.py"
    app_py.write_text(
        """
from flask import Flask, render_template, request

app = Flask(__name__)

@app.route('/')
def home():
    return 'Hello World'

@app.route('/api/users', methods=['GET', 'POST'])
def users():
    return 'Users'

@app.errorhandler(404)
def not_found(e):
    return 'Not Found', 404
"""
    )
    return temp_project_dir


@pytest.fixture
def sample_pydantic_project(temp_project_dir: Path) -> Path:
    """Create a sample project with Pydantic models."""
    models_py = temp_project_dir / "models.py"
    models_py.write_text(
        """
from pydantic import BaseModel, Field, validator

class User(BaseModel):
    name: str = Field(..., min_length=1)
    age: int = Field(..., ge=0, le=120)

    @validator('name')
    def name_must_be_alpha(cls, v):
        if not v.replace(' ', '').isalpha():
            raise ValueError('Name must contain only letters')
        return v

class Admin(User):
    level: int = 1

    class Config:
        validate_assignment = True
"""
    )
    return temp_project_dir


@pytest.fixture
def mock_file_system(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock file system operations."""

    def mock_exists(path: Any) -> bool:  # noqa: ARG001
        return True

    def mock_is_dir(path: Any) -> bool:  # noqa: ARG001
        return True

    def mock_read_text(path: Any) -> str:  # noqa: ARG001
        return "# Mock file content"

    monkeypatch.setattr(Path, "exists", mock_exists)
    monkeypatch.setattr(Path, "is_dir", mock_is_dir)
    monkeypatch.setattr(Path, "read_text", mock_read_text)


@pytest.fixture
def mock_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up mock environment variables."""
    monkeypatch.setenv("PYEYE_PACKAGES", "/path/to/pkg1:/path/to/pkg2")
    monkeypatch.setenv("PYEYE_NAMESPACE_company", "/repos/company-auth:/repos/company-api")
    monkeypatch.setenv("PYEYE_CACHE_TTL", "600")
