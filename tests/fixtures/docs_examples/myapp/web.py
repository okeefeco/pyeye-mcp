"""The web front end."""

from flask import Flask

app = Flask(__name__)


@app.route("/users/<int:user_id>", methods=["GET"])
def get_user(user_id: int) -> dict:
    """Return one user."""
    return {"id": user_id}
