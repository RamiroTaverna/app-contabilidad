from flask import Blueprint, render_template

bp = Blueprint("reports", __name__, url_prefix="/reports")

@bp.route("/")
def index():
    return render_template("reports/index.html")
