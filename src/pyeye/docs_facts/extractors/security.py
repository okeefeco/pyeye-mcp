"""Security facts: what the server runs, writes and rejects (#830, design C15).

SECURITY.md states these as facts, so they come from the code:

- the **server modules**: every pyeye module the server can import, following
  imports (module-level and function-local, absolute and relative) from
  ``pyeye.mcp.__main__``. Repository tooling the server never imports, such as
  :mod:`pyeye.docs_facts.changed`, is outside it by construction, not by a list;
- ``security.subprocesses``: the call sites in those modules that start a process;
- ``security.write_sites``: the call sites in those modules that write a file or
  create a directory;
- ``security.network_imports``: the imports of a networking module in those modules;
- ``security.metrics_inputs``: everything a tool call hands the usage-metrics
  recorder, the parameters of
  :meth:`pyeye.unified_metrics.UnifiedMetricsCollector.record_mcp_operation`;
- ``security.writes.config`` and ``security.writes.metrics``: where the two
  files the server keeps are written, from :data:`pyeye.constants.CONFIG_FILE`
  and :data:`pyeye.constants.METRICS_DIR`;
- ``security.path_checks.*``: what :meth:`pyeye.validation.PathValidator.validate_path`
  rejects, from its class constants, and which forms of a target it checks,
  from :meth:`~pyeye.validation.PathValidator.check_forms`' docstring;
- ``security.jedi_unsafe_extensions``: whether Jedi may load compiled extensions
  from outside the environment, from :data:`pyeye._jedi_project.LOAD_UNSAFE_EXTENSIONS`.

A site is ``module:qualname`` (the enclosing function or class), never a line
number, so the fact only changes when a site is added, removed or moved.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Iterator
from pathlib import Path

import pyeye

from ... import _jedi_project
from ...async_utils import filtered_rglob
from ...constants import CONFIG_FILE, METRICS_DIR
from ...path_utils import relative_within
from ...unified_metrics import UnifiedMetricsCollector
from ...validation import PathValidator
from ..facts import Bindable, ExtractionError, Fact, code, code_list, text, view

PREFIXES = ("security",)

#: The server's entry point (``python -m pyeye.mcp`` and the ``pyeye-mcp`` script).
ENTRY = "pyeye.mcp.__main__"

#: Calls that start a process: ``module -> attribute names``.
_PROCESS_CALLS: dict[str, frozenset[str]] = {
    "subprocess": frozenset(
        {"run", "call", "check_call", "check_output", "Popen", "getoutput", "getstatusoutput"}
    ),
    "os": frozenset(
        {"system", "popen", "posix_spawn", "posix_spawnp", "fork", "forkpty"}
        | {f"exec{s}" for s in ("l", "le", "lp", "lpe", "v", "ve", "vp", "vpe")}
        | {f"spawn{s}" for s in ("l", "le", "lp", "lpe", "v", "ve", "vp", "vpe")}
    ),
    "asyncio": frozenset({"create_subprocess_exec", "create_subprocess_shell"}),
    "multiprocessing": frozenset({"Process", "Pool"}),
    "concurrent.futures": frozenset({"ProcessPoolExecutor"}),
}

#: Modules that make network requests; importing one in a server module is a network site.
_NETWORK_MODULES = frozenset(
    {
        "socket",
        "ssl",
        "http",
        "urllib",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ftplib",
        "smtplib",
    }
)

#: Method names that write a file or create a directory, on any object.
_WRITE_METHODS = frozenset({"write_text", "write_bytes", "mkdir", "touch", "symlink_to"})
#: Module functions that write: ``module -> names``.
_WRITE_CALLS: dict[str, frozenset[str]] = {
    "os": frozenset({"makedirs", "mkdir", "replace", "rename", "remove", "unlink"}),
    "shutil": frozenset({"copy", "copy2", "copyfile", "copytree", "move", "rmtree"}),
    "logging": frozenset({"FileHandler"}),
}


def _module_name(rel: Path) -> str:
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(["pyeye", *parts])


def _modules(package: Path) -> dict[str, tuple[str, ast.Module]]:
    """Every pyeye module, parsed: dotted name -> (package-relative POSIX path, tree)."""
    found: dict[str, tuple[str, ast.Module]] = {}
    for path in sorted(filtered_rglob("*.py", package)):
        rel = relative_within(path, package)
        if rel is not None:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            found[_module_name(rel)] = (rel.as_posix(), tree)
    return found


def _imports(name: str, rel: str, tree: ast.Module, known: set[str]) -> set[str]:
    """The pyeye modules *tree* imports, anywhere in the module."""
    package = name if rel.endswith("__init__.py") else name.rsplit(".", 1)[0]
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
                base = f"{base}.{node.module}" if node.module else base
            else:
                base = node.module or ""
            targets = [base, *(f"{base}.{a.name}" for a in node.names)]
        else:
            continue
        for target in targets:
            # A submodule import also imports each parent package.
            parts = target.split(".")
            for i in range(1, len(parts) + 1):
                candidate = ".".join(parts[:i])
                if candidate in known:
                    out.add(candidate)
    return out


def server_modules(modules: dict[str, tuple[str, ast.Module]]) -> set[str]:
    """The import closure of :data:`ENTRY` within the pyeye package."""
    if ENTRY not in modules:
        raise ExtractionError(f"the server entry point {ENTRY} wasn't found")
    known = set(modules)
    seen: set[str] = set()
    todo = [ENTRY]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        rel, tree = modules[name]
        todo.extend(_imports(name, rel, tree, known) - seen)
    return seen


def _aliases(tree: ast.Module) -> tuple[dict[str, str], dict[str, str]]:
    """``(module aliases, imported names)``: local name -> module, and -> ``module.name``."""
    mods: dict[str, str] = {}
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods[a.asname or a.name.split(".")[0]] = (
                    a.name if a.asname else a.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                names[a.asname or a.name] = f"{node.module}.{a.name}"
    return mods, names


def _call_target(func: ast.expr, mods: dict[str, str], names: dict[str, str]) -> str | None:
    """``module.attr`` for a call on a module alias or an imported name, else None."""
    if isinstance(func, ast.Name):
        return names.get(func.id)
    if isinstance(func, ast.Attribute):
        chain: list[str] = [func.attr]
        value = func.value
        while isinstance(value, ast.Attribute):
            chain.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name) and value.id in mods:
            return ".".join([mods[value.id], *reversed(chain)])
    return None


def _matches(target: str | None, table: dict[str, frozenset[str]]) -> bool:
    if target is None:
        return False
    module, _, attr = target.rpartition(".")
    return attr in table.get(module, frozenset())


def _writes_by_mode(call: ast.Call, target: str | None) -> bool:
    """An ``open(...)`` / ``Path.open(...)`` whose mode writes (``w``, ``a``, ``x``, ``+``)."""
    is_open = (isinstance(call.func, ast.Name) and call.func.id == "open") or (
        isinstance(call.func, ast.Attribute) and call.func.attr == "open" and target is None
    )
    if not is_open:
        return False
    position = 1 if isinstance(call.func, ast.Name) else 0
    mode: ast.expr | None = call.args[position] if len(call.args) > position else None
    for kw in call.keywords:
        if kw.arg == "mode":
            mode = kw.value
    if mode is None:
        return False
    if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
        return True  # a computed mode might write: report it
    return any(ch in mode.value for ch in "wax+")


class _Sites(ast.NodeVisitor):
    """Collect process and write call sites, each named by its enclosing scope."""

    def __init__(self, module: str, tree: ast.Module) -> None:
        self.module = module
        self.mods, self.names = _aliases(tree)
        self.scope: list[str] = []
        self.process: set[str] = set()
        self.write: set[str] = set()
        self.network: set[str] = set()

    def _site(self) -> str:
        return f"{self.module}:{'.'.join(self.scope) or '<module>'}"

    def _scoped(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scoped  # noqa: N815

    def _imported(self, module: str) -> None:
        if module.split(".")[0] in _NETWORK_MODULES:
            self.network.add(f"{self._site()} imports {module}")

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802 - ast.NodeVisitor API
        for alias in node.names:
            self._imported(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802 - ast.NodeVisitor API
        if node.module and not node.level:
            self._imported(node.module)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802 - ast.NodeVisitor API
        target = _call_target(node.func, self.mods, self.names)
        if _matches(target, _PROCESS_CALLS):
            self.process.add(self._site())
        if (
            _matches(target, _WRITE_CALLS)
            or _writes_by_mode(node, target)
            or (
                target is None
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _WRITE_METHODS
            )
        ):
            self.write.add(self._site())
        self.generic_visit(node)


def _list(sites: list[str]) -> str:
    return code_list(sites) if sites else "none"


def _path_checks() -> Iterator[Bindable]:
    """What :meth:`PathValidator.validate_path` rejects, from its constants and docstring."""
    rejected = Fact(
        "security.path_checks.rejected",
        [described for _sequence, described in PathValidator.REJECTED_SEQUENCES],
        ", ".join(described for _sequence, described in PathValidator.REJECTED_SEQUENCES),
    )
    components = Fact(
        "security.path_checks.components",
        list(PathValidator.RESTRICTED_COMPONENTS),
        code_list(PathValidator.RESTRICTED_COMPONENTS),
    )
    targets = Fact(
        "security.path_checks.targets",
        list(PathValidator.RESTRICTED_TARGETS),
        code_list(PathValidator.RESTRICTED_TARGETS),
    )
    summary = (inspect.getdoc(PathValidator.check_forms) or "").split("\n", 1)[0]
    prefix = "``(resolved, forms)``: "
    if not summary.startswith(prefix):
        raise ExtractionError(
            "PathValidator.check_forms' docstring no longer starts with "
            f"{prefix!r}, so the checked forms can't be read from it"
        )
    forms = Fact("security.path_checks.forms", summary[len(prefix) :], text(summary[len(prefix) :]))
    yield from (rejected, components, targets, forms)
    yield view(
        "security.path_checks",
        [rejected, components, targets, forms],
        "\n".join(
            [
                f"- anywhere in the path: {rejected.markdown};",
                f"- naming one of these directories: {components.markdown};",
                f"- a target matching one of these patterns: {targets.markdown};",
                f"- forms checked: {forms.markdown}",
            ]
        ),
    )


def extract(root: Path) -> Iterator[Bindable]:  # noqa: ARG001 - reads the installed package
    """Yield the security facts."""
    modules = _modules(Path(pyeye.__file__).parent)
    process: set[str] = set()
    write: set[str] = set()
    network: set[str] = set()
    for name in sorted(server_modules(modules)):
        sites = _Sites(name, modules[name][1])
        sites.visit(modules[name][1])
        process |= sites.process
        write |= sites.write
        network |= sites.network

    subprocesses = sorted(process)
    yield Fact("security.subprocesses", subprocesses, _list(subprocesses))
    writes = sorted(write)
    yield Fact("security.write_sites", writes, _list(writes))
    networks = sorted(network)
    yield Fact("security.network_imports", networks, _list(networks))
    recorded = [
        name
        for name in inspect.signature(UnifiedMetricsCollector.record_mcp_operation).parameters
        if name != "self"
    ]
    yield Fact("security.metrics_inputs", recorded, code_list(recorded))

    config = Fact(
        "security.writes.config",
        {"path": f"<project_path>/{CONFIG_FILE}"},
        code(f"<project_path>/{CONFIG_FILE}"),
    )
    metrics = Fact(
        "security.writes.metrics", {"path": f"~/{METRICS_DIR}/"}, code(f"~/{METRICS_DIR}/")
    )
    yield config
    yield metrics
    yield view("security.writes", [config, metrics], f"{config.markdown}, {metrics.markdown}")

    yield from _path_checks()

    unsafe = _jedi_project.LOAD_UNSAFE_EXTENSIONS
    yield Fact("security.jedi_unsafe_extensions", unsafe, "on" if unsafe else "off")
