# app.py
from flask import Flask, render_template, session, g, current_app
from config import Config
from models import db, Usuario
from auth import bp as auth_bp, init_oauth

# Importa companies de forma explícita (si falla, verás el error y no habrá 404 silencioso)
from companies import bp as companies_bp

# Accounting puede ser opcional mientras tanto
try:
    from accounting import bp as accounting_bp
except Exception as e:
    print("[INFO] accounting blueprint no disponible:", e)
    accounting_bp = None


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # SQLAlchemy
    db.init_app(app)
    with app.app_context():
        db.create_all()

    # OAuth (Google)
    init_oauth(app)

    # Cargar usuario en cada request
    @app.before_request
    def load_user():
        g.user = None
        uid = session.get("uid")
        if uid:
            # Evita warning de SQLAlchemy 2.x
            g.user = db.session.get(Usuario, uid)

    # Variables globales para Jinja (en todas las plantillas)
    @app.context_processor
    def inject_globals():
        return dict(
            user=getattr(g, "user", None),
            current_app=current_app,
        )

    # Home
    @app.route("/")
    def home():
        return render_template(
            "home.html",
            has_companies=('companies' in app.blueprints),
            has_accounting=('accounting' in app.blueprints),
        )

    # Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(companies_bp)
    if accounting_bp:
        app.register_blueprint(accounting_bp)

    # Diagnóstico en consola
    print("BLUEPRINTS cargados:", list(app.blueprints.keys()))
    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
