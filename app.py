# app.py
from flask import Flask, render_template, session, g, current_app
from config import Config
from models import db, Usuario
from auth import bp as auth_bp, init_oauth

# si ya tenés estos blueprints, mantenelos:
try:
    from companies import bp as companies_bp
except Exception:
    companies_bp = None
try:
    from accounting import bp as accounting_bp
except Exception:
    accounting_bp = None

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    with app.app_context():
        db.create_all()

    init_oauth(app)

    @app.before_request
    def load_user():
        g.user = None
        uid = session.get("uid")
        if uid:
            g.user = Usuario.query.get(uid)

    # ✅ Registrar el context_processor DESPUÉS de crear la app
    @app.context_processor
    def inject_current_app():
        # opcional: podrías devolver flags en vez de exponer current_app entero
        return dict(current_app=current_app)

    @app.route("/")
    def home():
        return render_template("home.html", user=g.user)

    app.register_blueprint(auth_bp)
    if companies_bp:
        app.register_blueprint(companies_bp)
    if accounting_bp:
        app.register_blueprint(accounting_bp)

    return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
