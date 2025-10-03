# Testing Fixtures Guide

## Overview

Fixtures provide reusable test setup and teardown logic, ensuring consistent test environments and reducing code duplication.

## Fixture Organization

### Directory Structure

```text
tests/
├── conftest.py           # Root-level fixtures available to all tests
├── unit/
│   └── conftest.py      # Unit test specific fixtures
├── integration/
│   └── conftest.py      # Integration test fixtures
├── fixtures/            # Shared fixture data and factories
│   ├── __init__.py
│   ├── factories.py     # Test data factories
│   ├── projects/        # Sample project structures
│   └── data/           # Static test data files
```

## Core Fixtures

### Project Fixtures

```python
# tests/conftest.py
import pytest
from pathlib import Path
import tempfile

@pytest.fixture
def temp_project(tmp_path):
    """Create a temporary Python project structure."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    # Create basic structure
    (project_dir / "src").mkdir()
    (project_dir / "src" / "__init__.py").write_text("")
    (project_dir / "src" / "main.py").write_text("""
class MainClass:
    def method(self):
        return "result"
""")

    (project_dir / "tests").mkdir()
    (project_dir / "pyproject.toml").write_text("""
[project]
name = "test-project"
version = "0.1.0"
""")

    return project_dir

@pytest.fixture
def large_project(tmp_path):
    """Create a large project for performance testing."""
    project_dir = tmp_path / "large_project"
    project_dir.mkdir()

    # Create multiple packages
    for i in range(10):
        pkg_dir = project_dir / f"package_{i}"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")

        # Create multiple modules per package
        for j in range(10):
            module_content = f'''
class Class_{i}_{j}:
    """Class in package {i}, module {j}."""

    def method_{i}_{j}(self):
        """Method in class."""
        return "{i}_{j}"

def function_{i}_{j}():
    """Function in module."""
    return "result_{i}_{j}"

CONSTANT_{i}_{j} = "value_{i}_{j}"
'''
            (pkg_dir / f"module_{j}.py").write_text(module_content)

    return project_dir
```

### Configuration Fixtures

```python
# tests/conftest.py
@pytest.fixture
def mock_config():
    """Create mock configuration."""
    return {
        "packages": ["../lib1", "../lib2"],
        "namespaces": {
            "company": ["~/repos/auth", "~/repos/api"]
        },
        "cache_ttl": 300,
        "max_projects": 10
    }

@pytest.fixture
def config_file(tmp_path, mock_config):
    """Create configuration file."""
    import json
    config_path = tmp_path / ".pyeye.json"
    config_path.write_text(json.dumps(mock_config))
    return config_path
```

### Mock Fixtures

```python
# tests/conftest.py
from unittest.mock import Mock, AsyncMock

@pytest.fixture
def mock_analyzer():
    """Create mock Jedi analyzer."""
    analyzer = Mock()
    analyzer.find_symbol = Mock(return_value=[
        {"name": "TestClass", "type": "class", "line": 10}
    ])
    analyzer.get_references = Mock(return_value=[
        {"file": "test.py", "line": 20, "column": 5}
    ])
    return analyzer

@pytest.fixture
def mock_project_manager():
    """Create mock project manager."""
    manager = Mock()
    manager.get_project = AsyncMock()
    manager.cache = Mock()
    manager.namespace_resolver = Mock()
    return manager
```

## Fixture Factories

### Using Factory Boy

```python
# tests/fixtures/factories.py
import factory
from factory import Faker, SubFactory, LazyAttribute
from pyeye.models import Project, Symbol, Module

class ProjectFactory(factory.Factory):
    """Factory for creating test projects."""

    class Meta:
        model = Project

    name = Faker('word')
    path = LazyAttribute(lambda o: f"/tmp/projects/{o.name}")
    python_version = factory.Iterator(["3.10", "3.11", "3.12"])

    @factory.post_generation
    def modules(self, create, extracted, **kwargs):
        """Add modules to project."""
        if not create:
            return

        if extracted:
            for module in extracted:
                self.modules.append(module)

class SymbolFactory(factory.Factory):
    """Factory for creating test symbols."""

    class Meta:
        model = Symbol

    name = Faker('word')
    type = factory.Iterator(["class", "function", "variable"])
    file = LazyAttribute(lambda o: f"src/{o.name.lower()}.py")
    line = Faker('random_int', min=1, max=1000)
    column = Faker('random_int', min=0, max=120)

class ModuleFactory(factory.Factory):
    """Factory for creating test modules."""

    class Meta:
        model = Module

    name = Faker('word')
    path = LazyAttribute(lambda o: f"src/{o.name}.py")
    imports = factory.List([
        "os", "sys", "pathlib", "typing"
    ])
    exports = factory.LazyFunction(
        lambda: [SymbolFactory() for _ in range(5)]
    )
```

### Custom Factory Functions

```python
# tests/fixtures/factories.py
def create_test_file(path: Path, content: str = None) -> Path:
    """Create a test file with optional content."""
    if content is None:
        content = '''
def test_function():
    """Test function."""
    return "result"

class TestClass:
    """Test class."""

    def method(self):
        """Test method."""
        return "method_result"
'''

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path

def create_namespace_package(root: Path, namespace: str, packages: list) -> dict:
    """Create a namespace package structure."""
    namespace_parts = namespace.split('.')
    created_paths = []

    for package in packages:
        pkg_path = root / package
        current = pkg_path

        for part in namespace_parts:
            current = current / part
            current.mkdir(parents=True, exist_ok=True)
            init_file = current / "__init__.py"
            if not init_file.exists():
                init_file.write_text('__path__ = __import__("pkgutil").extend_path(__path__, __name__)')

        created_paths.append(pkg_path)

    return {
        "namespace": namespace,
        "paths": created_paths
    }
```

## Scope Management

### Fixture Scopes

```python
# Session scope - created once per test session
@pytest.fixture(scope="session")
def database():
    """Create test database for entire session."""
    db = create_test_database()
    yield db
    db.cleanup()

# Module scope - created once per test module
@pytest.fixture(scope="module")
def compiled_project():
    """Compile project once per module."""
    project = compile_test_project()
    yield project
    project.cleanup()

# Class scope - created once per test class
@pytest.fixture(scope="class")
def class_analyzer():
    """Create analyzer for test class."""
    analyzer = JediAnalyzer()
    yield analyzer
    analyzer.cleanup()

# Function scope (default) - created for each test
@pytest.fixture
def temp_cache():
    """Create temporary cache for each test."""
    cache = Cache(temp_dir())
    yield cache
    cache.clear()
```

## Parametrized Fixtures

```python
# tests/conftest.py
@pytest.fixture(params=["3.10", "3.11", "3.12"])
def python_version(request):
    """Parametrized Python version."""
    return request.param

@pytest.fixture(params=[
    {"type": "small", "modules": 5},
    {"type": "medium", "modules": 50},
    {"type": "large", "modules": 500}
])
def project_size(request):
    """Parametrized project sizes."""
    return request.param

# Usage in test
def test_with_different_versions(python_version):
    """Test runs 3 times with different Python versions."""
    assert python_version in ["3.10", "3.11", "3.12"]
```

## Async Fixtures

```python
# tests/conftest.py
import asyncio

@pytest.fixture
async def async_client():
    """Async client fixture."""
    client = AsyncClient()
    await client.connect()
    yield client
    await client.disconnect()

@pytest.fixture
async def async_cache():
    """Async cache fixture."""
    cache = AsyncCache()
    await cache.initialize()
    yield cache
    await cache.cleanup()

# Usage
@pytest.mark.asyncio
async def test_with_async_fixtures(async_client, async_cache):
    """Test using async fixtures."""
    await async_client.send("data")
    result = await async_cache.get("key")
    assert result is not None
```

## Fixture Dependencies

```python
# tests/conftest.py
@pytest.fixture
def base_config():
    """Base configuration."""
    return {"debug": True, "timeout": 30}

@pytest.fixture
def extended_config(base_config):
    """Extended configuration using base."""
    config = base_config.copy()
    config.update({
        "cache_size": 1000,
        "max_workers": 4
    })
    return config

@pytest.fixture
def configured_app(extended_config):
    """App configured with extended config."""
    app = Application(extended_config)
    return app
```

## Cleanup Patterns

### Using Yield

```python
@pytest.fixture
def resource_with_cleanup():
    """Resource that needs cleanup."""
    resource = acquire_resource()
    yield resource
    release_resource(resource)
```

### Using Finalizers

```python
@pytest.fixture
def resource_with_finalizer(request):
    """Resource with finalizer cleanup."""
    resource = acquire_resource()

    def cleanup():
        release_resource(resource)

    request.addfinalizer(cleanup)
    return resource
```

### Context Managers

```python
@pytest.fixture
def managed_resource():
    """Resource using context manager."""
    with acquire_resource() as resource:
        yield resource
    # Cleanup happens automatically
```

## Dynamic Fixtures

```python
# tests/conftest.py
def pytest_generate_tests(metafunc):
    """Dynamically generate test parameters."""
    if "test_data" in metafunc.fixturenames:
        test_cases = load_test_cases()
        metafunc.parametrize("test_data", test_cases)

@pytest.fixture
def dynamic_project(request):
    """Dynamic project based on test markers."""
    if request.node.get_closest_marker("large_project"):
        return create_large_project()
    elif request.node.get_closest_marker("small_project"):
        return create_small_project()
    else:
        return create_default_project()
```

## Shared Test Data

### Static Data Files

```python
# tests/fixtures/data/__init__.py
from pathlib import Path

DATA_DIR = Path(__file__).parent

def load_sample_code(name: str) -> str:
    """Load sample code file."""
    file_path = DATA_DIR / f"{name}.py"
    return file_path.read_text()

def load_test_config(name: str) -> dict:
    """Load test configuration."""
    import json
    file_path = DATA_DIR / f"{name}.json"
    return json.loads(file_path.read_text())
```

### Sample Projects

```python
# tests/fixtures/projects/__init__.py
from pathlib import Path
import shutil

PROJECTS_DIR = Path(__file__).parent

def copy_sample_project(name: str, dest: Path) -> Path:
    """Copy sample project to destination."""
    source = PROJECTS_DIR / name
    shutil.copytree(source, dest)
    return dest
```

## Performance Testing Fixtures

```python
# tests/performance/conftest.py
import time

@pytest.fixture
def timer():
    """Simple timer fixture."""
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    print(f"\nTest took {elapsed:.3f} seconds")

@pytest.fixture
def benchmark_data():
    """Generate data for benchmarking."""
    return {
        "small": generate_data(100),
        "medium": generate_data(1000),
        "large": generate_data(10000)
    }

@pytest.fixture
def performance_threshold():
    """Performance threshold fixture."""
    from tests.utils.performance import PerformanceThresholds
    return PerformanceThresholds(
        base=100.0,
        linux_ci=150.0,
        macos_ci=300.0,
        windows_ci=300.0
    )
```

## Best Practices

### DO

1. **Keep fixtures focused** - Each fixture should have a single responsibility
2. **Use appropriate scope** - Don't use session scope for data that changes
3. **Document fixtures** - Include docstrings explaining purpose and usage
4. **Handle cleanup** - Always clean up resources
5. **Make fixtures reusable** - Design for use across multiple tests

### DON'T

1. **Don't modify fixture data** - Fixtures should be immutable or reset between tests
2. **Don't use global state** - Fixtures should be isolated
3. **Don't make fixtures too complex** - Split complex fixtures into smaller ones
4. **Don't ignore cleanup** - Always release resources
5. **Don't hardcode paths** - Use tmp_path or relative paths

## Common Fixture Patterns

### Request Object

```python
@pytest.fixture
def configured_by_marker(request):
    """Configure based on test markers."""
    marker = request.node.get_closest_marker("config")
    if marker:
        return marker.args[0]
    return default_config()
```

### Indirect Parametrization

```python
@pytest.fixture
def project(request):
    """Create project based on parameter."""
    project_type = request.param
    if project_type == "django":
        return create_django_project()
    elif project_type == "flask":
        return create_flask_project()
    return create_basic_project()

@pytest.mark.parametrize("project", ["django", "flask"], indirect=True)
def test_with_different_projects(project):
    """Test with different project types."""
    assert project.is_valid()
```

### Autouse Fixtures

```python
@pytest.fixture(autouse=True)
def reset_environment():
    """Automatically reset environment for each test."""
    original = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(original)

@pytest.fixture(autouse=True)
def capture_logs(caplog):
    """Automatically capture logs for all tests."""
    caplog.set_level(logging.DEBUG)
    yield
    if caplog.records:
        print(f"\nCaptured {len(caplog.records)} log records")
```

## Debugging Fixtures

### Fixture Introspection

```python
def test_show_fixtures(request):
    """Show all fixtures available to test."""
    print("\nAvailable fixtures:")
    for fixture in request.fixturenames:
        print(f"  - {fixture}")
```

### Fixture Setup Order

```python
@pytest.fixture
def first():
    print("Setting up first")
    yield "first"
    print("Tearing down first")

@pytest.fixture
def second(first):
    print("Setting up second")
    yield "second"
    print("Tearing down second")

def test_order(second):
    """Observe fixture setup/teardown order."""
    print("Running test")
    # Output:
    # Setting up first
    # Setting up second
    # Running test
    # Tearing down second
    # Tearing down first
```

## References

- [Testing Strategy](./STRATEGY.md)
- [Testing Conventions](./CONVENTIONS.md)
- [pytest Fixtures Documentation](https://docs.pytest.org/en/stable/fixture.html)
- [Factory Boy Documentation](https://factoryboy.readthedocs.io/)
