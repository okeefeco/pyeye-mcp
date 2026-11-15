"""A nested module: corp.tools.sub.helper."""

import textwrap


def shout(text: str) -> str:
    """Upper-case and wrap *text*."""
    return textwrap.fill(text.upper(), width=40)
