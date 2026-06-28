"""Report handler -- PLANT 1 MINORITY (propagate). The CORRECT pattern.

This is the lone handler that does NOT swallow: it lets exceptions propagate
(and wraps-and-reraises to preserve context). It is the minority, but it is
the right behavior -- the prevalence trap is that the swallowers outnumber it.
"""

from app.core import config
from app.core.database import DB


class ReportError(Exception):
    pass


def handle_generate_report(report_id):
    # No try/except swallow: a failure here propagates to the caller.
    timeout = config.fetch_timeout()
    rows = DB.query("SELECT * FROM reports WHERE id = ?")
    return rows


def handle_export_report(report_id):
    try:
        return DB.query("SELECT * FROM report_exports")
    except Exception as exc:
        # PROPAGATE: wrap-and-reraise, preserving the original cause.
        raise ReportError("export failed") from exc
