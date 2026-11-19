"""Give a test project a virtualenv that has the test run's packages installed (#993).

Since #993 pyeye resolves a project's third-party imports from the PROJECT's
environment only, never from its own. A fixture that relies on an installed
package (pydantic, django, flask) therefore needs an environment of its own, as
a real project has. This builds one the way the production code reads it
(:mod:`pyeye.environment`): a ``.venv`` with a ``pyvenv.cfg`` and a
``site-packages`` whose ``.pth`` file names the running interpreter's
``purelib``. No symlink, so it works on Windows; no interpreter, since pyeye
never runs one.
"""

from __future__ import annotations

import sys
import sysconfig
from pathlib import Path


def give_installed_packages(project: Path) -> Path:
    """Create ``project/.venv`` whose site-packages reach this run's installed packages.

    Returns:
        The ``.venv`` directory.
    """
    venv = project / ".venv"
    major, minor = sys.version_info[:2]
    site = (
        venv / "Lib" / "site-packages"
        if sys.platform == "win32"
        else venv / "lib" / f"python{major}.{minor}" / "site-packages"
    )
    site.mkdir(parents=True, exist_ok=True)
    (venv / "pyvenv.cfg").write_text(f"version = {major}.{minor}.0\n", encoding="utf-8")
    purelib = Path(sysconfig.get_paths()["purelib"]).as_posix()
    (site / "_test_installed_packages.pth").write_text(f"{purelib}\n", encoding="utf-8")
    return venv
