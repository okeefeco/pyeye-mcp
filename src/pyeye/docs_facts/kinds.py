"""Built-in extractor kinds a repository's docs-facts config can name (#1091, C19).

A kind is a factory: the options a config table gives it, in; an
:class:`~.registry.Extractor`, out. The config names a kind and its options as
data, and the engine runs only code built into pyeye, never the analysed
repository's (ruling C19)::

    [[tool.pyeye.docs_facts.extractors]]
    kind = "structure"          # a key of BUILT_IN_KINDS
    include = ["pkg/**"]        # everything else is the kind's options
    prefix = "arch"

A factory validates its own options and raises :class:`KindOptionsError` (a
``ValueError``) on any it doesn't accept; the config loader reports it with
where in the config it is. The data-file kinds (``toml``/``json``/``yaml``)
are configured as ``facts`` entries instead (:mod:`.data_facts`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .registry import Extractor

#: A kind: its options (the config table, minus ``kind``) -> its extractor.
KindFactory = Callable[[Mapping[str, Any]], Extractor]


class KindOptionsError(ValueError):
    """A kind's options aren't valid: unknown, missing or of the wrong type."""


#: Every built-in kind, by the name a config's ``kind`` uses. #1092 adds
#: ``structure``; a kind is registered here, never named by a code reference.
BUILT_IN_KINDS: dict[str, KindFactory] = {}
