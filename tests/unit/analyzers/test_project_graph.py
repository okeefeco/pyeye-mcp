"""Unit tests for the per-project name-index store (#457, Task 2).

``project_graph`` caches a whole-project name->definitions index **outside** the
``file_artifact_cache`` LRU, keyed purely by project, built once and rebuilt only
on ``invalidate``. The load-bearing property: completeness can never depend on
the AST cache size (an evictable index = a name silently missing = #457 again).
"""

from pathlib import Path

from pyeye import file_artifact_cache
from pyeye.analyzers import project_graph


def _write(tmp_path: Path, rel: str, src: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src)
    return p


def test_index_collects_every_definition_of_a_name(tmp_path: Path) -> None:
    f1 = _write(tmp_path, "a.py", "class Field:\n    pass\n")
    f2 = _write(tmp_path, "b.py", "class Field:\n    pass\n")
    f3 = _write(tmp_path, "c.py", "class Other:\n    pass\n")
    project_graph.invalidate()
    idx = project_graph.get_name_index(str(tmp_path), [f1, f2, f3], {f1: "a", f2: "b", f3: "c"})
    assert {d.full_name for d in idx["Field"]} == {"a.Field", "b.Field"}
    assert len(idx["Field"]) == 2


def test_index_survives_ast_cache_clear(tmp_path: Path) -> None:
    # Completeness-not-behind-LRU: the index holds metadata, not ASTs, so
    # clearing the AST cache must not drop any definitions.
    f1 = _write(tmp_path, "a.py", "class Field:\n    pass\n")
    project_graph.invalidate()
    idx = project_graph.get_name_index(str(tmp_path), [f1], {f1: "a"})
    assert len(idx["Field"]) == 1

    file_artifact_cache.invalidate_all()

    idx2 = project_graph.get_name_index(str(tmp_path), [f1], {f1: "a"})
    assert idx2 is idx  # build-once: same cached object, no rebuild
    assert len(idx2["Field"]) == 1


def test_build_once_then_rebuild_after_invalidate(tmp_path: Path) -> None:
    f1 = _write(tmp_path, "a.py", "class Field:\n    pass\n")
    key = str(tmp_path)
    project_graph.invalidate()
    idx1 = project_graph.get_name_index(key, [f1], {f1: "a"})
    idx2 = project_graph.get_name_index(key, [f1], {f1: "a"})
    assert idx1 is idx2  # cached between calls

    project_graph.invalidate(key)
    idx3 = project_graph.get_name_index(key, [f1], {f1: "a"})
    assert idx3 is not idx1  # rebuilt after invalidate


def test_freshness_reflects_edits_after_invalidate(tmp_path: Path) -> None:
    f1 = _write(tmp_path, "a.py", "class Field:\n    pass\n")
    key = str(tmp_path)
    project_graph.invalidate()
    idx = project_graph.get_name_index(key, [f1], {f1: "a"})
    assert "NewClass" not in idx

    f1.write_text("class Field:\n    pass\n\n\nclass NewClass:\n    pass\n")
    file_artifact_cache.invalidate(f1)
    project_graph.invalidate(key)

    idx2 = project_graph.get_name_index(key, [f1], {f1: "a"})
    assert "NewClass" in idx2


def test_distinct_projects_do_not_collide(tmp_path: Path) -> None:
    fa = _write(tmp_path, "proj_a/m.py", "class A:\n    pass\n")
    fb = _write(tmp_path, "proj_b/m.py", "class B:\n    pass\n")
    project_graph.invalidate()
    idx_a = project_graph.get_name_index(str(tmp_path / "proj_a"), [fa], {fa: "m"})
    idx_b = project_graph.get_name_index(str(tmp_path / "proj_b"), [fb], {fb: "m"})
    assert "A" in idx_a and "B" not in idx_a
    assert "B" in idx_b and "A" not in idx_b


def test_definitions_are_deterministically_ordered(tmp_path: Path) -> None:
    f1 = _write(tmp_path, "z.py", "class Field:\n    pass\n")
    f2 = _write(tmp_path, "a.py", "class Field:\n    pass\n")
    project_graph.invalidate()
    idx = project_graph.get_name_index(str(tmp_path), [f1, f2], {f1: "z", f2: "a"})
    paths = [d.module_path.as_posix() for d in idx["Field"]]
    assert paths == sorted(paths)  # sorted by posix path regardless of input order


def test_cache_invalidate_file_clears_name_index(tmp_path: Path) -> None:
    # The watcher path (GranularCache.invalidate_file) must drop the index.
    from pyeye.cache import GranularCache

    f1 = _write(tmp_path, "a.py", "class Field:\n    pass\n")
    key = tmp_path.as_posix()
    project_graph.invalidate()
    idx1 = project_graph.get_name_index(key, [f1], {f1: "a"})

    GranularCache().invalidate_file(f1)

    idx2 = project_graph.get_name_index(key, [f1], {f1: "a"})
    assert idx2 is not idx1  # file change cleared the index -> rebuilt


def test_project_eviction_clears_name_index(tmp_path: Path) -> None:
    # Eviction-invalidation must fire so a non-evicting index does not leak.
    from pyeye.project_manager import ProjectManager

    f1 = _write(tmp_path, "a.py", "class Field:\n    pass\n")
    key = tmp_path.as_posix()
    project_graph.invalidate()
    idx1 = project_graph.get_name_index(key, [f1], {f1: "a"})

    ProjectManager()._cleanup_project(tmp_path)

    idx2 = project_graph.get_name_index(key, [f1], {f1: "a"})
    assert idx2 is not idx1  # eviction cleared this project's index -> rebuilt


def test_index_includes_a_module_entry_per_file(tmp_path: Path) -> None:
    f = _write(tmp_path, "auth.py", "class X:\n    pass\n")
    project_graph.invalidate()
    idx = project_graph.get_name_index(str(tmp_path), [f], {f: "acme.auth"})
    mods = [d for d in idx.get("auth", []) if d.type == "module"]
    assert len(mods) == 1
    assert mods[0].full_name == "acme.auth"
    assert mods[0].module_path == f


def test_regular_package_indexed_via_its_init(tmp_path: Path) -> None:
    # A regular package (dir with __init__.py) is indexed via that __init__.py,
    # under the package's short name, with the package's dotted full_name.
    f = _write(tmp_path, "models/__init__.py", "")
    project_graph.invalidate()
    idx = project_graph.get_name_index(str(tmp_path), [f], {f: "django.db.models"})
    pkgs = [d for d in idx.get("models", []) if d.type == "module"]
    assert len(pkgs) == 1
    assert pkgs[0].full_name == "django.db.models"


def test_methods_are_not_top_level_index_entries(tmp_path: Path) -> None:
    # Methods/attributes are reached via the parent at lookup, never indexed by
    # bare name.
    f = _write(tmp_path, "m.py", "class C:\n    attr = 1\n    def method(self):\n        pass\n")
    project_graph.invalidate()
    idx = project_graph.get_name_index(str(tmp_path), [f], {f: "m"})
    assert "C" in idx  # the class is a top-level entry
    assert "method" not in idx  # its method is not
    assert "attr" not in idx  # nor its attribute
