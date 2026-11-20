"""``_names_path`` compares Jedi's own name; the #814 respelling is retired (#971).

#814 added a respelling: Jedi named a configured package nested in the project
from the project root (``.hidden.upstream.clonepkg.thing.X``), so a candidate's
``full_name`` was respelled through the file -> module mapper before the
comparison. #858 (PR #966) put every configured package on Jedi's own
sys_path, so Jedi's names now agree with the mapper. Measured before
retiring it: the respelling produced no match in the whole test suite, nor in
14,620 ``_names_path`` calls on django.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pyeye import resolver


def _name(name: str, full_name: str | None) -> SimpleNamespace:
    return SimpleNamespace(name=name, full_name=full_name)


@pytest.fixture
def no_mapper(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_a: object) -> None:
        raise AssertionError("_names_path must not respell through the mapper (#971)")

    monkeypatch.setattr(resolver, "handle_for_anchor", refuse)


@pytest.mark.usefixtures("no_mapper")
class TestNamesPath:
    def test_its_own_name_matches(self) -> None:
        assert resolver._names_path(_name("X", "pkg.mod.X"), "pkg.mod.X") is True

    def test_another_spelling_of_the_same_qualname_does_not(self) -> None:
        """The case the respelling used to rescue: now a plain mismatch, never a mapper call."""
        candidate = _name("X", ".hidden.upstream.pkg.mod.X")

        assert resolver._names_path(candidate, "pkg.mod.X") is False

    def test_a_different_leaf_or_no_full_name_does_not(self) -> None:
        assert resolver._names_path(_name("Y", "pkg.mod.Y"), "pkg.mod.X") is False
        assert resolver._names_path(_name("X", None), "pkg.mod.X") is False
