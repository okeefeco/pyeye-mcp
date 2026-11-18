"""The grep-tracking wrappers run the real command and count code searches (#969).

``setup_grep_tracking.sh`` installs ``~/.local/bin/{grep,egrep,fgrep,rg}``, each
``exec grep_tracker.sh <cmd> "$@"``. The tracker used to take the command from
``basename "$0"`` (its own name), so it counted nothing and every wrapped call
failed with exit 127. These run the real setup in a temporary HOME and call the
generated wrappers end to end.
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404 - runs this repo's scripts and the system grep
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the wrappers are bash scripts")

_REPO = Path(__file__).resolve().parents[1]
_SETUP = _REPO / "scripts" / "setup_grep_tracking.sh"
_METRICS = _REPO / "scripts" / "dogfooding_metrics.py"

# A pre-#969 wrapper, byte for byte the old template (the tracker path filled in).
_OLD_WRAPPER = """#!/bin/bash
# Auto-generated grep tracker wrapper for dogfooding metrics
export DOGFOODING_PROJECT_ROOT="{root}/scripts/.."
exec "{root}/scripts/grep_tracker.sh" "grep" "$@"
"""


def _env(home: Path) -> dict[str, str]:
    real_home = Path.home()
    env = {
        "HOME": str(home),
        "PATH": f"{home / '.local' / 'bin'}:/usr/local/bin:/usr/bin:/bin",
        # uv's cache and managed Pythons stay where they are; only HOME moves.
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(real_home / ".cache" / "uv")),
        "UV_PYTHON_INSTALL_DIR": os.environ.get(
            "UV_PYTHON_INSTALL_DIR", str(real_home / ".local" / "share" / "uv" / "python")
        ),
    }
    uv_dir = os.path.dirname(
        subprocess.run(  # nosec B603 B607
            ["bash", "-c", "command -v uv"], capture_output=True, text=True, check=False
        ).stdout.strip()
    )
    if uv_dir:
        env["PATH"] += f":{uv_dir}"
    return env


def _run(args: list[str], home: Path, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed commands from this repo  # nosec B603
        args, capture_output=True, text=True, timeout=120, check=False, env=_env(home), cwd=cwd
    )


@pytest.fixture
def home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".bashrc").write_text("# test rc\n", encoding="utf-8")
    return home


def _setup(home: Path) -> Path:
    result = _run(["bash", str(_SETUP)], home)
    assert result.returncode == 0, result.stdout + result.stderr
    return home / ".local" / "bin"


def test_setup_installs_the_four_wrappers_and_the_path_line_once(home: Path) -> None:
    bin_dir = _setup(home)
    assert sorted(p.name for p in bin_dir.iterdir()) == ["egrep", "fgrep", "grep", "rg"]
    _setup(home)  # a re-run adds no second PATH line
    rc = (home / ".bashrc").read_text(encoding="utf-8")
    assert rc.count('export PATH="$HOME/.local/bin:$PATH"') <= 1


def test_the_wrapper_runs_the_real_grep(home: Path, tmp_path: Path) -> None:
    bin_dir = _setup(home)
    sample = tmp_path / "sample.txt"
    sample.write_text("alpha\ndef beta\n", encoding="utf-8")

    found = _run([str(bin_dir / "grep"), "-n", "beta", str(sample)], home)
    assert (found.returncode, found.stdout) == (0, "2:def beta\n"), found.stderr

    missing = _run([str(bin_dir / "grep"), "gamma", str(sample)], home)
    assert (missing.returncode, missing.stdout) == (1, "")  # grep's own "no match"

    bad = _run([str(bin_dir / "grep"), "x", str(tmp_path / "nope.txt")], home)
    assert bad.returncode == 2  # grep's own error status, not the tracker's 127

    egrep = _run([str(bin_dir / "egrep"), "-c", "al|be", str(sample)], home)
    assert (egrep.returncode, egrep.stdout.strip()) == (0, "2")


def test_a_rerun_repairs_pre_969_wrappers_already_on_path(home: Path, tmp_path: Path) -> None:
    """The broken wrappers are first on PATH while setup runs; it must not use them."""
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    old = bin_dir / "grep"
    old.write_text(_OLD_WRAPPER.format(root=_REPO.as_posix()), encoding="utf-8")
    old.chmod(0o755)

    _setup(home)
    sample = tmp_path / "s.txt"
    sample.write_text("x\n", encoding="utf-8")
    assert _run([str(bin_dir / "grep"), "x", str(sample)], home).returncode == 0


def test_an_old_wrapper_finds_the_real_grep_instead_of_itself(home: Path, tmp_path: Path) -> None:
    """With the fixed tracker, even a never-regenerated wrapper works and can't loop."""
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    old = bin_dir / "grep"
    old.write_text(_OLD_WRAPPER.format(root=_REPO.as_posix()), encoding="utf-8")
    old.chmod(0o755)
    sample = tmp_path / "s.txt"
    sample.write_text("x\n", encoding="utf-8")
    result = _run([str(old), "x", str(sample)], home)
    assert (result.returncode, result.stdout) == (0, "x\n"), result.stderr


def test_a_code_search_is_counted_and_a_plain_one_is_not(home: Path, tmp_path: Path) -> None:
    bin_dir = _setup(home)
    started = _run(
        ["uv", "run", "--frozen", "--project", str(_REPO), "python", str(_METRICS), "start"]
        + ["--issue", "969"],
        home,
    )
    assert started.returncode == 0, started.stderr
    src = tmp_path / "src"
    src.mkdir()
    (src / "m.py").write_text("def f():\n    pass\n", encoding="utf-8")

    assert _run([str(bin_dir / "grep"), "-r", "def f", str(src)], home).returncode == 0
    # Not a code search: a plain word, a .txt file, no -r (a *.py argument counts too)
    notes = tmp_path / "notes.txt"
    notes.write_text("pass the salt\n", encoding="utf-8")
    assert _run([str(bin_dir / "grep"), "salt", str(notes)], home).returncode == 0

    session = json.loads((home / ".pyeye" / "metrics" / "current_session.json").read_text())
    assert session["grep_count"] == 1


def test_the_tracker_refuses_to_run_without_a_command(home: Path) -> None:
    result = _run(["bash", str(_REPO / "scripts" / "grep_tracker.sh")], home)
    assert result.returncode == 2
    assert "usage" in result.stderr


def test_a_command_missing_from_path_is_reported_not_looped(home: Path) -> None:
    result = _run(
        ["bash", str(_REPO / "scripts" / "grep_tracker.sh"), "no-such-grep-969", "x"], home
    )
    assert result.returncode == 127
    assert "not found on PATH" in result.stderr
