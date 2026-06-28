"""Report service -- PLANT 5 cluster C: returns a tuple result-shape.

Also the PLANT 4 CONTRAST case: this service takes its database dependency by
PARAMETER INJECTION (the `db` argument), unlike the handlers that reach for
the app.core.database module-global singleton.
"""

from app.core import config
from app.handlers import report_handler


def load_report(report_id, db):
    # db is INJECTED, not taken from the module global. Contrast PLANT 4.
    rows = db.query("SELECT * FROM reports WHERE id = ?")
    report = report_handler.handle_generate_report(report_id)
    # Result-shape: tuple -- same concept as user_service dict / order_service dataclass.
    return (True, report, None)
