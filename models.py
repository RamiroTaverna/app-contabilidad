# models.py
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Enum
import enum

db = SQLAlchemy()

class Rol(enum.Enum):
    docente = "docente"
    empleado = "empleado"
    dueno = "dueno"

class Usuario(db.Model):
    __tablename__ = "usuarios"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    correo = db.Column(db.String(100), unique=True, nullable=False)
    contrasena_hash = db.Column(db.String(255))  # por si luego agregás login propio
    rol = db.Column(Enum(Rol), default=Rol.empleado, nullable=False)
    google_sub = db.Column(db.String(255), unique=True)  # id estable de Google
