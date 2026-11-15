"""Entry point that pulls in all three namespace repos."""

import sys

from corp.core.models import Base, make
from corp.tools import Base as ReexportedBase
from corp.tools.widgets import Widget
from corp.web.views import render


def run() -> str:
    """Use one symbol from each repo."""
    assert ReexportedBase is Base
    sys.stdout.write(render(make("x")))
    return Widget("w").describe()
