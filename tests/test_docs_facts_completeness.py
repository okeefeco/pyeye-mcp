"""Each fact family is checked against a signal its extractor doesn't use, or says why it has none (#1120).

An extractor finds only what it was written to find. A new concept, or a value
read a new way, gives no fact and no failure, and the ledger only lists facts
that exist. So each family in :data:`pyeye.docs_facts.registry.EXTRACTORS`
names here either a test that compares its facts to an independent signal, or
a one-line reason it has none. A new family fails until it's declared.

One small test per family, not a framework (the maintainer's ask).
"""

from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

from pyeye.docs_facts.extractors import env
from pyeye.docs_facts.facts import Fact
from pyeye.docs_facts.registry import EXTRACTORS

_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Signal:
    """A test that checks the family's facts against something its extractor doesn't read."""

    test: str  # pytest node id, relative to the repo root


@dataclass(frozen=True)
class Reason:
    """Why the family has no independent signal."""

    text: str


FAMILIES: dict[str, Signal | Reason] = {
    # The live MCP server's registered tools.
    "mcp_surface": Signal(
        "tests/test_docs_facts_extractors.py::TestMcpSurface::test_core_tools_are_the_registered_ones"
    ),
    # The live edge registry, which the server's descriptions render (#1098, #1118).
    "edges": Signal("tests/test_docs_facts_describe.py::test_every_static_load_time_fact_is_live"),
    # A text scan of src/ for environment reads (below).
    "env": Signal(
        "tests/test_docs_facts_completeness.py::TestEnv::test_every_read_has_a_fact_and_back"
    ),
    "cli": Reason(
        "the facts are the declarations themselves: [project.scripts] and the __main__.py "
        "files are the only ways to define an entry point"
    ),
    "ci": Reason(
        "read from the files that define CI and packaging; every pattern must match and the "
        "files must agree with each other, or extraction fails"
    ),
    # The architecture-review taxonomy, imported.
    "review": Signal(
        "tests/test_docs_facts_skill_extractors.py::test_every_seed_axis_is_a_fact_with_its_taxonomy"
    ),
    # A hand-written list of the CLI's commands and flags: a new one fails until it's reviewed.
    "duplication": Signal(
        "tests/test_docs_facts_skill_extractors.py::test_duplication_vocabulary_is_the_parsers"
    ),
    # The live scope constants, which the server's descriptions render (#1098, #1118).
    "scopes": Signal("tests/test_docs_facts_describe.py::test_every_static_load_time_fact_is_live"),
    # What PathValidator actually rejects, called live.
    "security": Signal(
        "tests/test_docs_facts_security.py::TestFacts::test_path_checks_match_what_validate_path_rejects"
    ),
    # The resolver run live: it consults exactly the tables the facts list, in order.
    "resolver": Signal(
        "tests/test_docs_facts_resolver.py::TestTables::test_resolve_runs_exactly_the_tables_in_order"
    ),
    "repo_config": Reason(
        "pre-commit hooks come from the file that defines them (no hook ids fails extraction), "
        "and config keys from pyeye.config.CONFIG_KEYS, the tuple the loader itself accepts"
    ),
}


class TestEveryFamily:
    def test_declares_a_signal_or_a_reason(self) -> None:
        assert set(FAMILIES) == {e.name for e in EXTRACTORS}

    @pytest.mark.parametrize(
        "family", [n for n, s in FAMILIES.items() if isinstance(s, Signal)], ids=str
    )
    def test_its_signal_test_exists(self, family: str) -> None:
        signal = FAMILIES[family]
        assert isinstance(signal, Signal)
        path, *names = signal.test.split("::")
        scope: list[ast.stmt] = ast.parse((_ROOT / path).read_text(encoding="utf-8")).body
        for name in names:
            found = [
                n
                for n in scope
                if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == name
            ]
            assert found, f"{family}: {signal.test} names {name!r}, which doesn't exist"
            scope = found[0].body if isinstance(found[0], ast.ClassDef) else []

    @pytest.mark.parametrize(
        "family", [n for n, s in FAMILIES.items() if isinstance(s, Reason)], ids=str
    )
    def test_its_reason_is_stated(self, family: str) -> None:
        reason = FAMILIES[family]
        assert isinstance(reason, Reason) and len(reason.text.split()) >= 5


# ---------------------------------------------------------------------------
# env: every environment read in src/ has an env.* fact, and every fact a read
# ---------------------------------------------------------------------------

#: A read: ``environ.get(...)``, ``environ.setdefault(...)``, ``environ.pop(...)``,
#: ``environ[...]`` or ``getenv(...)``, with its first argument. Text, not the
#: extractor's AST walk, so a read it doesn't recognise still shows here.
_READ = re.compile(
    r"\benviron\s*(?:\.\s*(?:get|setdefault|pop)\s*\(|\[)\s*(?P<a>[^,)\]]+)"
    r"|\bgetenv\s*\(\s*(?P<b>[^,)]+)"
)
#: A settings loader, ``self._get_<kind>_env("NAME", ...)``, of any kind.
_LOADER = re.compile(r"\b_get_\w+_env\s*\(\s*['\"](?P<name>\w+)['\"]")
_STRING = re.compile(r"""^(['"])(?P<name>\w+)\1$""")

#: Reads whose name isn't a literal at the call, and where the names come from.
INDIRECT_READS = {
    # The loaders' own body: every name reaches it through a _get_*_env call (_LOADER).
    ("settings.py", "key"),
    # The activated environment, VIRTUAL_ENV then CONDA_PREFIX: not pyeye's own variables.
    ("environment.py", "var"),
}
#: Variables pyeye reads but doesn't own, so they aren't env.* facts.
EXTERNAL_VARS: frozenset[str] = frozenset()
#: The env extractor quotes the read forms in its own docstrings.
NOT_SCANNED = {"docs_facts/extractors/env.py"}


def env_reads(package: Path) -> tuple[set[str], list[str]]:
    """The literal names read in *package*, and the reads it can't name (``file: arg``)."""
    names: set[str] = set()
    unnamed: list[str] = []
    for path in sorted(package.rglob("*.py")):
        rel = path.relative_to(package).as_posix()
        if rel in NOT_SCANNED:
            continue
        text = path.read_text(encoding="utf-8")
        names.update(m["name"] for m in _LOADER.finditer(text))
        for m in _READ.finditer(text):
            arg = (m["a"] or m["b"]).strip()
            literal = _STRING.match(arg)
            if literal:
                names.add(literal["name"])
            elif (rel, arg) not in INDIRECT_READS:
                unnamed.append(f"{rel}: {arg}")
    return names, unnamed


def env_gaps(root: Path) -> dict[str, list[str]]:
    """What the env facts and the text scan disagree on, for the checkout at *root*."""
    facts = {f.id[len("env.") :] for f in env.extract(root) if isinstance(f, Fact)}
    names, unnamed = env_reads(root / "src" / "pyeye")
    owned = {n for n in names if n not in EXTERNAL_VARS}
    return {
        "read_without_a_fact": sorted(owned - facts),
        "fact_without_a_read": sorted(facts - owned),
        "read_the_scan_cannot_name": unnamed,
    }


class TestEnv:
    def test_every_read_has_a_fact_and_back(self) -> None:
        assert env_gaps(_ROOT) == {
            "read_without_a_fact": [],
            "fact_without_a_read": [],
            "read_the_scan_cannot_name": [],
        }

    def test_a_read_the_extractor_misses_fails(self, tmp_path: Path) -> None:
        """A loader of a new kind (``_get_path_env``) is a read the extractor doesn't know."""
        package = tmp_path / "src" / "pyeye"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "settings.py").write_text(
            textwrap.dedent("""\
                DEPRECATED_ENV_VARS: dict[str, str] = {}


                class Settings:
                    def __init__(self) -> None:
                        self.known: int = self._get_int_env("PYEYE_KNOWN", 1)
                        self.new: str = self._get_path_env("PYEYE_NEW", "")
                """),
            encoding="utf-8",
        )
        (package / "user.py").write_text(
            "from .settings import Settings\n\nS = Settings()\nprint(S.known, S.new)\n",
            encoding="utf-8",
        )

        gaps = env_gaps(tmp_path)

        assert gaps["read_without_a_fact"] == ["PYEYE_NEW"]

    def test_a_read_through_a_variable_fails(self, tmp_path: Path) -> None:
        package = tmp_path / "pyeye"
        package.mkdir()
        (package / "mod.py").write_text(
            "import os\n\nNAME = pick()\nos.environ.get(NAME)\n", encoding="utf-8"
        )

        assert env_reads(package)[1] == ["mod.py: NAME"]
