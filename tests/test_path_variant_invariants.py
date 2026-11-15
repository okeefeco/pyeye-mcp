"""The same project reached by another path spelling gives the same answers (#717).

The #614 cross-tool invariants run each corpus at one spelling of its root.
These runs reach the same project through other spellings of the same root and
require **identical** answers: the same handles, ``found`` / not-found results,
kinds, scopes, edge counts and stub sets. Three path bugs in one afternoon
(#710, #714, #715) all came from a root spelled differently from what Jedi or
the OS reported.

Variants
--------
- ``symlink``: the corpus's parent directory reached through a symlink, so
  configured siblings such as ``../acme-repo`` still resolve. This is macOS's
  ``/var`` -> ``/private/var`` case, reproduced on Linux.
- ``dotdot``: the root spelled ``<parent>/<root>/../<root>``.
- ``relative``: the root given relative to the working directory.
- ``drive_case``: Windows only, the drive letter in the other case.

The analyzer is a bare ``JediAnalyzer`` built with the corpus's config, because
``ProjectManager.get_analyzer`` resolves its key and would collapse every
variant to the plain run.

Allow-list contract
-------------------
Same rules as ``tests/test_cross_tool_invariants.py``: :data:`KNOWN_GAPS` maps
an exact difference to the issue that removes it. A difference not on the list
fails, and a listed one that no longer reproduces fails too, so the entry gets
deleted.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from pyeye import file_artifact_cache
from pyeye.analyzers import project_graph
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.config import ProjectConfig
from pyeye.mcp.operations import typeref
from pyeye.mcp.operations.edges import EDGE_RESOLVERS
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve
from pyeye.path_utils import paths_equal
from tests.test_cross_tool_invariants import _EXTRA_SEEDS, _SWEEP_CORPORA, _module_seeds

_FIXTURES = Path(__file__).parent / "fixtures"

#: One corpus per project shape: plain modules and re-exports, a PEP 420
#: namespace, a root package, a configured namespace repo outside the root
#: (relative ``../`` config), and a configured ``src/`` layout. The ``src/``
#: layout is the shape #714 broke: without it these runs passed on the buggy
#: code. The full #614 corpus set runs at the plain spelling in
#: ``test_cross_tool_invariants``.
_ROOTS: dict[str, Path] = {
    **{
        name: _SWEEP_CORPORA[name]
        for name in (
            "cross_tool",
            "canonicalization_multihop",
            "ns420",
            "lookup_project",
            "xns_repo",
            "multirepo_namespace",
        )
    },
    "src_layout": _FIXTURES / "added_sys_path_project",
}
_VARIANT_CORPORA = tuple(_ROOTS)

#: Per-PR runs cover the corpora that catch #714-class bugs: a flat layout (the
#: members edge's ``__main__`` stubs), a configured ``src/`` layout, and a
#: namespace repo reached by a relative ``../`` config. The rest run when
#: ``PYEYE_EXHAUSTIVE_PATHS=1``, which CI's push-to-main job sets.
_EXHAUSTIVE_ENV = "PYEYE_EXHAUSTIVE_PATHS"
_PER_PR_CORPORA = frozenset({"cross_tool", "src_layout", "xns_repo"})


def _corpus_params(names: Iterable[str]) -> list[Any]:
    exhaustive = os.environ.get(_EXHAUSTIVE_ENV) == "1"
    return [
        pytest.param(
            name,
            marks=pytest.mark.skipif(
                name not in _PER_PR_CORPORA and not exhaustive,
                reason=f"exhaustive path run; set {_EXHAUSTIVE_ENV}=1",
            ),
        )
        for name in sorted(names)
    ]


_VARIANTS = ("symlink", "dotdot", "relative", "drive_case")

#: (variant, corpus, kind, key...) -> issue whose fix removes the difference.
KNOWN_GAPS: dict[tuple[str, ...], str] = {}

#: Bound on project members followed per corpus, keeping the runs quick.
_MAX_SOURCES = 60


def _cold_caches() -> None:
    """Start each run cold, as a server opened on that root would.

    The process-wide caches key on resolved paths, so a warm cache from the
    plain run hands a variant run Scripts built for the real root. That hid #714
    from an earlier draft of this test.
    """
    file_artifact_cache.invalidate_all()
    project_graph.invalidate()
    typeref.invalidate_all()


def _analyzer(root: str | Path) -> JediAnalyzer:
    return JediAnalyzer(str(root), config=ProjectConfig(str(root)))


async def _observe(corpus: str, analyzer: JediAnalyzer) -> dict[tuple[str, ...], Any]:
    """Everything the tools answer for *corpus*, keyed so two runs can be diffed.

    Paths are left out of the values, because a variant keeps its own spelling
    in ``location.file`` (#603). ``_file`` keys hold each answer's file so the
    test can check that both runs point at the same file on disk.
    """
    _cold_caches()
    real_root = _ROOTS[corpus]
    queue = _module_seeds(real_root) + _EXTRA_SEEDS.get(corpus, [])
    seen: set[str] = set()
    out: dict[tuple[str, ...], Any] = {}
    emitted: set[str] = set()
    while queue and len(seen) < _MAX_SOURCES:
        source = queue.pop(0)
        if source in seen:
            continue
        seen.add(source)
        node = await inspect(source, analyzer)
        out[("inspect", source)] = (
            node.get("found"),
            node.get("handle"),
            node.get("kind"),
            node.get("scope"),
            tuple(sorted((node.get("edge_counts") or {}).items())),
        )
        if node.get("location"):
            out[("_file", "inspect", source)] = node["location"]["file"]
        for edge in EDGE_RESOLVERS:
            result = await expand(source, edge, analyzer)
            stubs = result.get("stubs")
            out[("expand", source, edge)] = (
                result.get("found"),
                result.get("reason"),
                None if stubs is None else tuple(sorted(s["handle"] for s in stubs)),
            )
            for stub in stubs or []:
                emitted.add(stub["handle"])
                if edge == "members" and stub.get("scope") == "project":
                    queue.append(stub["handle"])
    for handle in sorted(emitted):
        res = await resolve(handle, analyzer)
        out[("resolve", handle)] = (res.get("found"), res.get("handle"), res.get("ambiguous"))
        if res.get("location"):
            out[("_file", "resolve", handle)] = res["location"]["file"]
    # Bare names go through the name index over the listed files, a different
    # path from FQN lookup (#714 broke only this one under a symlinked root).
    for leaf in sorted({h.rsplit(".", 1)[-1] for h in emitted}):
        res = await resolve(leaf, analyzer)
        handles = [res.get("handle")] + [c["handle"] for c in res.get("candidates", [])]
        out[("resolve_bare", leaf)] = (res.get("found"), tuple(sorted(h for h in handles if h)))
    return out


_PLAIN: dict[str, dict[tuple[str, ...], Any]] = {}


async def _plain(corpus: str) -> dict[tuple[str, ...], Any]:
    if corpus not in _PLAIN:
        _PLAIN[corpus] = await _observe(corpus, _analyzer(_ROOTS[corpus]))
    return _PLAIN[corpus]


def _variant_root(variant: str, corpus: str, tmp_path: Path, monkeypatch: Any) -> str:
    root = _ROOTS[corpus]
    if variant == "symlink":
        if sys.platform == "win32":
            pytest.skip("creating symlinks needs privileges on Windows")
        link = tmp_path / "link"
        link.symlink_to(root.parent, target_is_directory=True)
        return (link / root.name).as_posix()
    if variant == "dotdot":
        return f"{root.as_posix()}/../{root.name}"
    if variant == "relative":
        monkeypatch.chdir(root.parent)
        return root.name
    if variant == "drive_case":
        if sys.platform != "win32":
            pytest.skip("drive letters exist only on Windows")
        text = os.fspath(root)
        return text[0].swapcase() + text[1:]
    raise AssertionError(variant)


def _differences(
    variant: str,
    corpus: str,
    plain: dict[tuple[str, ...], Any],
    other: dict[tuple[str, ...], Any],
) -> dict[tuple[str, ...], str]:
    out: dict[tuple[str, ...], str] = {}
    for key in sorted(set(plain) | set(other), key=repr):
        if key[0] == "_file":
            if key not in plain or key not in other:
                continue
            # The same file on disk. Its spelling may differ: Jedi reports
            # files with symlinks resolved, so location.file isn't always in
            # the caller's spelling of the root.
            if not paths_equal(plain[key], other[key]):
                out[(variant, corpus, *key)] = f"{plain[key]!r} vs {other[key]!r}"
            continue
        if plain.get(key, "<absent>") != other.get(key, "<absent>"):
            out[(variant, corpus, *key)] = (
                f"plain {plain.get(key, '<absent>')!r} != {variant} {other.get(key, '<absent>')!r}"
            )
    return out


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", _VARIANTS)
@pytest.mark.parametrize("corpus", _corpus_params(_VARIANT_CORPORA))
async def test_a_path_variant_gives_identical_answers(
    corpus: str, variant: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = await _plain(corpus)
    assert any(k[0] == "expand" for k in plain), f"{corpus}: the run observed nothing"
    root = _variant_root(variant, corpus, tmp_path, monkeypatch)

    other = await _observe(corpus, _analyzer(root))

    observed = _differences(variant, corpus, plain, other)
    allowed = {k: v for k, v in KNOWN_GAPS.items() if k[:2] == (variant, corpus)}
    new = sorted(set(observed) - set(allowed), key=repr)
    fixed = sorted(set(allowed) - set(observed), key=repr)
    lines = [f"NEW difference {k!r}: {observed[k]}" for k in new]
    lines += [f"no longer reproduces, delete from KNOWN_GAPS: {k!r} # {allowed[k]}" for k in fixed]
    assert not lines, f"{variant}[{corpus}]:\n" + "\n".join(lines[:40])


def test_known_gaps_name_real_variants_and_corpora() -> None:
    for key, issue in KNOWN_GAPS.items():
        assert key[0] in _VARIANTS and key[1] in _VARIANT_CORPORA, key
        assert issue.startswith("#"), (key, issue)
