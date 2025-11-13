# config.py
import os
from dotenv import load_dotenv, find_dotenv  # pip install python-dotenv (opcional si usás .env)
load_dotenv(find_dotenv())

class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "mysql+pymysql://root:@localhost/sistema_contable")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")

    # ❌ NO hardcodear secretos
    OAUTH_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    OAUTH_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:5000/auth/callback")

    GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
    DEV_FAKE_LOGIN = os.getenv("DEV_FAKE_LOGIN", "false").lower() in ("1", "true", "yes")

