# auth.py
from __future__ import annotations
import json, glob
from typing import Optional

from flask import (
    Blueprint, redirect, url_for, session, request, abort,
    current_app as app, render_template
)
from authlib.integrations.flask_client import OAuth
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, Usuario, Rol
from auth_forms import LoginForm, RegisterForm

bp = Blueprint("auth", __name__, url_prefix="/auth")
oauth = OAuth()

# -------- Helpers credenciales --------
def _load_google_creds_from_json() -> Optional[dict]:
    try:
        for path in glob.glob("client_secret_*.json"):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            web = data.get("web") or {}
            client_id = web.get("client_id")
            client_secret = web.get("client_secret")
            redirect_uris = web.get("redirect_uris") or []
            redirect_uri = redirect_uris[0] if redirect_uris else None
            if client_id and client_secret:
                return {"client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri}
    except Exception:
        pass
    return None

def init_oauth(flask_app):
    oauth.init_app(flask_app)

    # 1) Desde config/env
    client_id = flask_app.config.get("OAUTH_CLIENT_ID") or flask_app.config.get("GOOGLE_CLIENT_ID")
    client_secret = flask_app.config.get("OAUTH_CLIENT_SECRET") or flask_app.config.get("GOOGLE_CLIENT_SECRET")
    redirect_uri = flask_app.config.get("OAUTH_REDIRECT_URI") or flask_app.config.get("GOOGLE_REDIRECT_URI")

    # 2) Si faltan, usar client_secret_*.json
    if not client_id or not client_secret:
        creds = _load_google_creds_from_json()
        if creds:
            client_id = client_id or creds.get("client_id")
            client_secret = client_secret or creds.get("client_secret")
            redirect_uri = redirect_uri or creds.get("redirect_uri")

    if not client_id or not client_secret:
        raise RuntimeError("Google OAuth no configurado: define OAUTH_CLIENT_ID/SECRET o coloca client_secret_*.json.")

    flask_app.config["OAUTH_CLIENT_ID"] = client_id
    flask_app.config["OAUTH_CLIENT_SECRET"] = client_secret
    if redirect_uri:
        flask_app.config["OAUTH_REDIRECT_URI"] = redirect_uri

    # Registrar proveedor con api_base_url (para /userinfo)
    oauth.register(
        name="google",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url=flask_app.config.get("GOOGLE_DISCOVERY_URL"),
        api_base_url="https://openidconnect.googleapis.com/v1/",
        client_kwargs={"scope": "openid email profile"},
    )
    return oauth

# -------- Rutas auth --------
@bp.route("/login")
def login():
    redirect_uri = app.config.get("OAUTH_REDIRECT_URI") or url_for("auth.callback", _external=True)
    # soporte ?next=/ruta
    next_url = request.args.get("next")
    if next_url:
        session["login_next"] = next_url
    app.logger.info(f"[LOGIN] redirect_uri={redirect_uri}")
    return oauth.google.authorize_redirect(redirect_uri)

@bp.route("/callback")
def callback():
    try:
        token = oauth.google.authorize_access_token()
        app.logger.info(f"[CALLBACK] token keys: {list(token.keys())}")

        # userinfo con api_base_url ya definido
        resp = oauth.google.get("userinfo")
        userinfo = resp.json()
        app.logger.info(f"[CALLBACK] userinfo: {userinfo}")
    except Exception as e:
        app.logger.exception(f"[CALLBACK] Exception: {e}")
        return f"OAuth error: {e}", 400

    if not userinfo or not userinfo.get("email"):
        return "No se pudo obtener userinfo/email desde Google.", 400

    sub = userinfo.get("sub")
    email = userinfo.get("email")
    name = userinfo.get("name") or (email.split("@")[0] if email else "Usuario")

    user = Usuario.query.filter(
        (Usuario.google_sub == sub) | (Usuario.correo == email)
    ).first()

    if not user:
        user = Usuario(nombre=name, correo=email, google_sub=sub, rol=Rol.empleado)
        db.session.add(user)
    else:
        if not user.google_sub:
            user.google_sub = sub
        if name and user.nombre != name:
            user.nombre = name

    db.session.commit()
    session["uid"] = user.id
    app.logger.info(f"[CALLBACK] Login OK -> uid={user.id}, {user.nombre}")

    next_url = session.pop("login_next", None) or url_for("home")
    return redirect(next_url)

@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@bp.route("/devlogin")
def devlogin():
    if not app.config.get("DEV_FAKE_LOGIN", True):
        return "Dev login deshabilitado", 403
    user = Usuario.query.filter_by(correo="dev@local.test").first()
    if not user:
        user = Usuario(nombre="Dev Empleado", correo="dev@local.test", rol=Rol.empleado)
        db.session.add(user); db.session.commit()
    session["uid"] = user.id
    return redirect(url_for("home"))

@bp.route("/login_form", methods=["GET", "POST"])
def login_form():
    # For security/UX: use Google OAuth interface instead of local inputs.
    # Redirect to the OAuth login flow. Preserve ?next= if present.
    next_url = request.args.get("next")
    if next_url:
        session["login_next"] = next_url
    return redirect(url_for("auth.login", next=next_url))

@bp.route("/register", methods=["GET", "POST"])
def register():
    # Registration through the web form is disabled in favor of Google OAuth.
    # Redirect users to the Google login flow which will create accounts on callback.
    next_url = request.args.get("next")
    if next_url:
        session["login_next"] = next_url
    return redirect(url_for("auth.login", next=next_url))
