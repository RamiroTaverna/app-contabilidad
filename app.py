# app.py
from flask import Flask, render_template, session, g, current_app
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
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

# Nuevos blueprints: admin y reports
try:
    from admin import bp as admin_bp
except Exception as e:
    print("[INFO] admin blueprint no disponible:", e)
    admin_bp = None

try:
    from reports import bp as reports_bp
except Exception as e:
    print("[INFO] reports blueprint no disponible:", e)
    reports_bp = None

csrf = CSRFProtect()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    csrf.init_app(app)

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
            csrf_token=generate_csrf,
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
    if admin_bp:
        app.register_blueprint(admin_bp)
    if reports_bp:
        app.register_blueprint(reports_bp)

    # Diagnóstico en consola
    print("BLUEPRINTS cargados:", list(app.blueprints.keys()))
    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
