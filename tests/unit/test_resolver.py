"""Tests for the one canonical handle resolver, :mod:`pyeye.resolver` (#623 slice 2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from pyeye import resolver as resolver_mod
from pyeye._module_sentinel import ModuleSentinel
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.resolver import NotFound, Resolved, resolve_handle

# Canonical (definition-site) handle for ``pathlib.Path``; it moved to
# ``pathlib._local`` in Python 3.13 (#529).
_PATH_CLASS_HANDLE = f"{Path.__module__}.Path"


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


@pytest.fixture
def project(tmp_path: Path) -> JediAnalyzer:
    """A small project covering every strategy the resolver tries."""
    _write(
        tmp_path,
        {
            "pkg/__init__.py": '"""Package."""\nfrom pkg._impl import Thing\nINIT_ONLY = 1\n',
            "pkg/_impl.py": (
                "class Thing:\n"
                '    """A thing."""\n'
                "    def method(self) -> int:\n"
                "        return 1\n"
            ),
            "pkg/plain.py": "VALUE = 2\n\ndef helper() -> None:\n    pass\n",
            "nspkg/portion.py": "X = 1\n",
        },
    )
    return JediAnalyzer(str(tmp_path))


def _resolved(path: str, analyzer: JediAnalyzer) -> Resolved:
    result = resolve_handle(path, analyzer)
    assert isinstance(result, Resolved), f"{path!r} did not resolve: {result}"
    return result


# ---------------------------------------------------------------------------
# Step 1 / 2 — project modules and PEP 420 namespace packages
# ---------------------------------------------------------------------------


def test_project_package_and_module(project: JediAnalyzer) -> None:
    pkg = _resolved("pkg", project)
    assert (pkg.handle, pkg.kind, pkg.scope) == ("pkg", "module", "project")
    plain = _resolved("pkg.plain", project)
    assert (plain.handle, plain.kind, plain.scope) == ("pkg.plain", "module", "project")


def test_namespace_package_is_a_dir_anchored_module(project: JediAnalyzer) -> None:
    ns = _resolved("nspkg", project)
    assert ns.handle == "nspkg"
    assert ns.kind == "module"
    assert isinstance(ns.anchor, ModuleSentinel)
    assert ns.anchor.module_path is not None and ns.anchor.module_path.is_dir()


# ---------------------------------------------------------------------------
# Step 3 — external modules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", ["logging", "os", "typing", "collections.abc"])
def test_external_module(project: JediAnalyzer, module: str) -> None:
    result = _resolved(module, project)
    assert (result.handle, result.kind, result.scope) == (module, "module", "external")


def test_os_path_resolves_to_a_platform_module(project: JediAnalyzer) -> None:
    """``os.path`` resolves; which platform module it anchors on stays with #329."""
    result = _resolved("os.path", project)
    assert (result.handle, result.kind, result.scope) == ("os.path", "module", "external")


# ---------------------------------------------------------------------------
# Step 4 — definition placement and aliases
# ---------------------------------------------------------------------------


def test_definition_in_deepest_module(project: JediAnalyzer) -> None:
    thing = _resolved("pkg._impl.Thing", project)
    assert (thing.handle, thing.kind, thing.scope) == ("pkg._impl.Thing", "class", "project")
    method = _resolved("pkg._impl.Thing.method", project)
    assert (method.handle, method.kind) == ("pkg._impl.Thing.method", "method")
    helper = _resolved("pkg.plain.helper", project)
    assert (helper.handle, helper.kind) == ("pkg.plain.helper", "function")


def test_reexport_alias_reports_the_canonical_handle(project: JediAnalyzer) -> None:
    """#431: the alias resolves, and the canonical handle is what callers echo."""
    thing = _resolved("pkg.Thing", project)
    assert thing.handle == "pkg._impl.Thing"
    assert thing.kind == "class"
    assert thing.anchor.module_path.name == "_impl.py"


def test_member_through_an_alias(project: JediAnalyzer) -> None:
    method = _resolved("pkg.Thing.method", project)
    assert (method.handle, method.kind) == ("pkg._impl.Thing.method", "method")


def test_placement_stops_at_the_deepest_module(project: JediAnalyzer) -> None:
    """No fallback to a shallower module after a miss (#623, one placement step).

    ``INIT_ONLY`` is defined in ``pkg/__init__.py``, but ``pkg.plain`` is the
    deepest module along ``pkg.plain.INIT_ONLY`` and doesn't define it.
    """
    assert isinstance(resolve_handle("pkg.plain.INIT_ONLY", project), NotFound)
    assert _resolved("pkg.INIT_ONLY", project).handle == "pkg.INIT_ONLY"


class _NoFullName:
    """Wrap a Jedi ``Name`` so its ``full_name`` match misses (the #419 flake)."""

    def __init__(self, name: Any) -> None:
        self._name = name
        self.full_name = None

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._name, attr)


def test_definition_found_by_name_when_full_name_match_flakes(
    project: JediAnalyzer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#419/#429: a missed ``full_name`` match is placed by name + goto, deterministically."""
    real_get_script = resolver_mod.file_artifact_cache.get_script

    class _FlakyScript:
        def __init__(self, script: Any) -> None:
            self._script = script

        def get_names(self, **kwargs: Any) -> list[Any]:
            return [_NoFullName(n) for n in self._script.get_names(**kwargs)]

    def flaky(path: Path, jedi_project: Any) -> Any:
        script = real_get_script(path, jedi_project)
        return _FlakyScript(script) if path.name == "plain.py" else script

    monkeypatch.setattr(resolver_mod.file_artifact_cache, "get_script", flaky)
    helper = _resolved("pkg.plain.helper", project)
    assert (helper.handle, helper.kind) == ("pkg.plain.helper", "function")


# ---------------------------------------------------------------------------
# Step 5 — guarded inference (external only)
# ---------------------------------------------------------------------------


def test_external_class_resolves_to_its_definition(project: JediAnalyzer) -> None:
    result = _resolved("pathlib.Path", project)
    assert (result.handle, result.kind, result.scope) == (_PATH_CLASS_HANDLE, "class", "external")


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("typing.TYPE_CHECKING", "variable"),  # infers to bool
        ("typing.Dict", "variable"),  # infers to the class typing.dict
        ("__future__.annotations", "variable"),  # infers to a _Feature instance
        ("typing.ClassVar", "function"),  # infers to _SpecialForm
    ],
)
def test_external_name_is_placed_at_its_definition(
    project: JediAnalyzer, path: str, kind: str
) -> None:
    """#506 for externals (#623 slice 5): the definition at the requested path wins.

    Inference answers "what value is this?", which for these names is another
    object; goto lands on the definition at exactly this path, so the name is
    its own canonical handle.
    """
    result = _resolved(path, project)
    assert (result.handle, result.kind, result.scope) == (path, kind, "external")


@pytest.mark.parametrize("path", ["collections.abc.Mapping", "os.sep"])
def test_definition_elsewhere_and_mismatched_inference_are_not_found(
    project: JediAnalyzer, path: str
) -> None:
    """An honest miss, not a wrong answer (#544).

    ``collections.abc.Mapping``'s goto lands on ``typing.Mapping`` (typeshed's
    reversed claim) and it infers to ``_SpecialGenericAlias``; ``os.sep`` goes to
    a platform module and infers to ``str``.  Neither is the requested path.
    """
    assert isinstance(resolve_handle(path, project), NotFound)


def test_inference_never_runs_inside_the_project(project: JediAnalyzer) -> None:
    """#506: a project handle is placed by definition lookup, never inferred."""
    with patch.object(
        resolver_mod, "_synthetic_import", wraps=resolver_mod._synthetic_import
    ) as spy:
        assert isinstance(resolve_handle("pkg.plain.missing", project), NotFound)
    assert spy.call_count == 0


@pytest.mark.parametrize("path", ["totally.bogus.DoesNotExist9999", "nonexistent_module_xyz"])
def test_unknown_handle_is_not_found(project: JediAnalyzer, path: str) -> None:
    result = resolve_handle(path, project)
    assert isinstance(result, NotFound)
    assert result.reason == "unresolved"
    assert path in result.detail


def test_synthetic_import_failure_is_not_found(project: JediAnalyzer) -> None:
    with patch("jedi.Script", side_effect=RuntimeError("simulated jedi failure")):
        assert isinstance(resolve_handle("pathlib.Path", project), NotFound)
        assert isinstance(resolve_handle("logging", project), NotFound)


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["", "a..b", ".lead", "trail.", "has space"])
def test_malformed_path_is_not_found(project: JediAnalyzer, path: str) -> None:
    assert isinstance(resolve_handle(path, project), NotFound)


def test_internal_error_is_not_found(
    project: JediAnalyzer, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: Any) -> None:
        raise RuntimeError("layout exploded")

    monkeypatch.setattr(resolver_mod, "file_for_module", boom)
    assert isinstance(resolve_handle("pkg", project), NotFound)


def test_alias_hops_are_bounded(project: JediAnalyzer) -> None:
    assert (
        resolver_mod._follow_alias("pkg", ["Thing"], [], project, resolver_mod._MAX_ALIAS_HOPS)
        is None
    )
