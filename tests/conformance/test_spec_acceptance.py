"""Spec acceptance tests — one class per acceptance criterion.

These tests are intentionally redundant with the unit and integration tests.
Their purpose is spec traceability: each class maps to a numbered acceptance
criterion from the resolve/inspect API design so that a future reader can
immediately see whether the project meets its stated contract.

Acceptance criteria covered here:

    4. (partial) Empirical wire-format ratio vs LSP-bridge baseline.
       inspect ≤ 0.3× the LSP-bridge canonical-copy byte count.

    6. Re-export canonicality: ``resolve("package.Config")`` and
       ``resolve("package._impl.config.Config")`` return the same handle
       when Config is re-exported; ``inspect`` on that handle lists
       ``package.Config`` in re_exports.

    7. (partial, inspect-side) Project/external boundary: inspecting an
       external handle returns scope="external" with shallow data; the
       subclasses edge count reflects project-internal subclasses only.

Note on criterion 7: the expand() operation (deferred past Phase 7) is not
tested here.  The test covers the inspect()-side contract only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).parent.parent / "fixtures"
_CANON_BASIC = _FIXTURES / "canonicalization_basic"
_RESOLVE_PROJECT = _FIXTURES / "resolve_project"


def _make_analyzer(project_path: Path):
    """Create a JediAnalyzer pointed at *project_path*."""
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer

    return JediAnalyzer(str(project_path))


# ===========================================================================
# Spec acceptance criterion 6 — re-export canonicality
# ===========================================================================


class TestReExportCanonicality:
    """Spec acceptance criterion 6: re-export canonicality.

    ``resolve("package.Config")`` and
    ``resolve("package._impl.config.Config")`` must return the same handle
    when Config is re-exported at package/__init__.py.  Inspecting that
    canonical handle must list ``"package.Config"`` in re_exports.

    This test is intentionally redundant with canonicalization unit tests and
    Phase 6 inspect tests.  It exists purely for spec traceability: if you
    want to know whether acceptance criterion 6 passes, look here.
    """

    @pytest.mark.asyncio
    async def test_both_paths_resolve_to_same_handle(self) -> None:
        """Spec criterion 6: public and private paths resolve to the same handle.

        package.Config (the re-export path) and
        package._impl.config.Config (the definition site) must produce
        identical handle strings when resolved.
        """
        from pyeye.mcp.operations.resolve import resolve

        analyzer = _make_analyzer(_CANON_BASIC)

        r_public = await resolve("package.Config", analyzer)
        r_private = await resolve("package._impl.config.Config", analyzer)

        assert (
            r_public.get("found") is True
        ), f"resolve('package.Config') expected found=True, got: {r_public!r}"
        assert (
            r_private.get("found") is True
        ), f"resolve('package._impl.config.Config') expected found=True, got: {r_private!r}"

        handle_public = r_public["handle"]
        handle_private = r_private["handle"]

        assert handle_public == handle_private, (
            f"Re-export canonicality failure: "
            f"'package.Config' → {handle_public!r} but "
            f"'package._impl.config.Config' → {handle_private!r}. "
            f"Both must resolve to the same canonical handle (the definition site)."
        )

    @pytest.mark.asyncio
    async def test_canonical_handle_inspects_to_include_reexport_path(self) -> None:
        """Spec criterion 6: inspect on the canonical handle lists the re-export path.

        After resolving package.Config to its canonical handle, calling
        inspect() on that handle must return a node whose re_exports list
        contains "package.Config" — i.e. the public re-export path.
        """
        from pyeye.mcp.operations.inspect import inspect
        from pyeye.mcp.operations.resolve import resolve

        analyzer = _make_analyzer(_CANON_BASIC)

        r = await resolve("package.Config", analyzer)
        assert r.get("found") is True
        canonical_handle = r["handle"]

        node = await inspect(canonical_handle, analyzer)

        assert "re_exports" in node, (
            f"inspect({canonical_handle!r}) must include 're_exports'; "
            f"got keys: {list(node.keys())}"
        )
        assert "package.Config" in node["re_exports"], (
            f"inspect({canonical_handle!r}).re_exports must contain 'package.Config'; "
            f"got: {node['re_exports']!r}"
        )


# ===========================================================================
# Spec acceptance criterion 7 — project/external boundary
# ===========================================================================


class TestProjectExternalBoundary:
    """Spec acceptance criterion 7: project/external boundary (inspect side).

    Verifies that inspecting an external handle (stdlib class) returns
    scope="external" with shallow structural data, and that
    edge_counts.subclasses reflects project-internal subclasses only.

    External symbol used: pathlib.PurePath (stdlib, universally available).

    The fixture file ``tests/fixtures/resolve_project/mypackage/
    external_subclass_demo.py`` defines ``_ProjectPathExtension(PurePath)``
    so that exactly one project-internal subclass exists.  The test asserts
    edge_counts["subclasses"] == 1, not the much larger number of subclasses
    that Python's stdlib itself contains (PurePosixPath, PureWindowsPath, etc.).

    Note: expand() is deferred past Phase 7.  This test covers only the
    inspect()-side of criterion 7.
    """

    @pytest.mark.asyncio
    async def test_external_handle_returns_external_scope(self) -> None:
        """Spec criterion 7: inspect on a stdlib class returns scope='external'."""
        from pyeye.mcp.operations.inspect import inspect

        # Use resolve_project fixture — it has the _ProjectPathExtension fixture file.
        analyzer = _make_analyzer(_RESOLVE_PROJECT)
        node = await inspect("pathlib.PurePath", analyzer)

        assert node.get("scope") == "external", (
            f"inspect('pathlib.PurePath') expected scope='external'; "
            f"got scope={node.get('scope')!r}"
        )

    @pytest.mark.asyncio
    async def test_external_handle_returns_shallow_data(self) -> None:
        """Spec criterion 7: inspect on external handle returns universal fields.

        All inspect responses must include the universal fields regardless of
        scope.  This verifies no KeyError / missing field on an external symbol.
        """
        from pyeye.mcp.operations.inspect import inspect

        analyzer = _make_analyzer(_RESOLVE_PROJECT)
        node = await inspect("pathlib.PurePath", analyzer)

        # Universal fields required on ALL inspect responses
        for field in ("handle", "kind", "scope", "location", "edge_counts"):
            assert field in node, (
                f"inspect('pathlib.PurePath') missing required field {field!r}; "
                f"got keys: {list(node.keys())}"
            )

        # Verify no source content leaks (layering principle)
        loc = node["location"]
        for banned in ("source", "text", "snippet", "body", "code"):
            assert banned not in loc, (
                f"location must not contain {banned!r} (layering violation); "
                f"got location={loc!r}"
            )

    @pytest.mark.asyncio
    async def test_external_subclasses_count_is_project_scoped(self) -> None:
        """Spec criterion 7: edge_counts.subclasses is project-scoped.

        The fixture defines exactly one project-internal class extending
        pathlib.PurePath (_ProjectPathExtension in external_subclass_demo.py).
        The subclasses count must be 1 — reflecting only project-internal
        subclasses, NOT the stdlib's own PurePosixPath / PureWindowsPath /
        etc. which would inflate the count if scope filtering were absent.
        """
        from pyeye.mcp.operations.inspect import inspect

        # Use resolve_project fixture which contains the _ProjectPathExtension class.
        # The fixture file is:
        #   tests/fixtures/resolve_project/mypackage/external_subclass_demo.py
        analyzer = _make_analyzer(_RESOLVE_PROJECT)
        node = await inspect("pathlib.PurePath", analyzer)

        edge_counts = node.get("edge_counts", {})
        assert "subclasses" in edge_counts, (
            f"inspect('pathlib.PurePath').edge_counts must contain 'subclasses'; "
            f"got edge_counts={edge_counts!r}"
        )

        actual = edge_counts["subclasses"]
        assert actual == 1, (
            f"edge_counts['subclasses'] must be 1 (project-scoped: only "
            f"_ProjectPathExtension from external_subclass_demo.py); "
            f"got {actual!r}.  If this is >1, scope filtering may be absent. "
            f"If 0, the fixture file may not be in the project scope."
        )


# ===========================================================================
# Spec acceptance criterion 4 (partial) — wire-format ratio
# ===========================================================================


class TestWireFormatRatio:
    """Spec acceptance criterion 4: inspect ≤ 0.3× LSP-bridge baseline.

    Verifies that the inspect() response for a representative project class
    is materially smaller than what an LSP-bridge tool would return when
    shipping the full source file.

    Baseline
    --------
    2026-05-02 measurement: mcp-language-server's ``definition`` call on the
    GranularCache class returned approximately 470 lines / ~17,500 bytes
    (canonical copy; both copies together were ~35,000 bytes).

    The canonical-copy figure (17,500 bytes) is used as the baseline.

    Do NOT recompute this baseline at test time — LSP-bridge behaviour drifts
    as pyright-lsp and mcp-language-server change.  Hard-coding makes the test
    fail for a known reason (pyeye regression) rather than mysteriously.

    Floor target: inspect response ≤ 0.30× the 17,500-byte baseline.
    Expected actual ratio: ~0.02–0.10× (pyeye ships no source content).
    """

    # Baseline: 17,500 bytes from 2026-05-02 mcp-language-server definition
    # call on GranularCache (canonical copy; both copies were ~35,000 bytes).
    # Update only if methodology changes (different bridge, different fixture,
    # different version).
    LSP_BRIDGE_BASELINE_BYTES = 17_500

    # Conservative floor — beating this by a wide margin is expected.
    # If the ratio approaches 0.3×, source content is likely leaking.
    INSPECT_RATIO_FLOOR = 0.30

    @pytest.mark.asyncio
    async def test_inspect_granularcache_is_under_floor(self) -> None:
        """inspect response on GranularCache must be ≤ 0.3× LSP-bridge baseline.

        Actual measurement is expected to be much smaller (~0.02–0.10×) because
        pyeye ships no source content.  The 0.3× floor is intentionally
        conservative; beating it comfortably is expected.  If the ratio
        approaches 0.3×, content is leaking somewhere — check the layering
        linter (Phase 7.1) and the spec's layering principle.

        GranularCache is at pyeye.cache.GranularCache (src/pyeye/cache.py).
        It is a large class (~234 lines) chosen to match the 2026-05-02
        baseline measurement.
        """
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer
        from pyeye.mcp.operations.inspect import inspect

        # Use the actual pyeye-mcp project as the analyzer root.
        analyzer = JediAnalyzer(".")
        result = await inspect("pyeye.cache.GranularCache", analyzer)

        wire_bytes = len(json.dumps(result).encode("utf-8"))
        ratio = wire_bytes / self.LSP_BRIDGE_BASELINE_BYTES

        assert ratio <= self.INSPECT_RATIO_FLOOR, (
            f"inspect response on GranularCache is {wire_bytes} bytes "
            f"({ratio:.3f}× the {self.LSP_BRIDGE_BASELINE_BYTES}-byte LSP-bridge baseline). "
            f"Floor is {self.INSPECT_RATIO_FLOOR}×. If you're hitting this, content is leaking; "
            f"check the layering linter (Phase 7.1) and the spec's layering principle."
        )

    @pytest.mark.asyncio
    async def test_inspect_granularcache_ratio_observability(self) -> None:
        """Print the actual ratio for visibility (informational; never fails alone).

        Running the conformance suite with ``-s`` / ``--capture=no`` shows the
        ratio so a developer can see how far pyeye is under the floor without
        having to compute it manually.

        As of 2026-05-02: actual ratio ~0.030× (527 bytes vs 17,500-byte
        baseline).  This is 10× better than the 0.3× floor.
        """
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer
        from pyeye.mcp.operations.inspect import inspect

        analyzer = JediAnalyzer(".")
        result = await inspect("pyeye.cache.GranularCache", analyzer)

        wire_bytes = len(json.dumps(result).encode("utf-8"))
        ratio = wire_bytes / self.LSP_BRIDGE_BASELINE_BYTES

        print(
            f"\ninspect/LSP-bridge ratio for GranularCache: "
            f"{ratio:.3f}× ({wire_bytes} bytes vs "
            f"{self.LSP_BRIDGE_BASELINE_BYTES}-byte baseline)"
        )
        # No assertion — purely informational.  The strict floor is in
        # test_inspect_granularcache_is_under_floor above.
