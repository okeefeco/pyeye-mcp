"""The admin area: a blueprint, a class-based view, an error page and a CLI command."""

from flask import Blueprint, render_template
from flask.views import MethodView
from flask_login import LoginManager

from .web import app

admin = Blueprint("admin", __name__, url_prefix="/admin")
login_manager = LoginManager(app)


@admin.route("/")
def dashboard() -> str:
    """Show the admin dashboard."""
    return render_template("admin.html")


class UserAdmin(MethodView):
    """List users for an administrator."""

    def get(self) -> dict:
        """Return the users this view manages."""
        return {"view": type(self).__name__}


@app.errorhandler(404)
def not_found(error: Exception) -> tuple[str, int]:
    """Render the not-found page."""
    return f"not found: {error}", 404


@app.cli.command()
def seed() -> None:
    """Load demo data."""
    print("seeded")


app.register_blueprint(admin)
