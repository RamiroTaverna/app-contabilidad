# models.py
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Enum, UniqueConstraint, ForeignKey
from sqlalchemy.orm import relationship
import enum

db = SQLAlchemy()

# --------- Enum de roles ---------
class Rol(enum.Enum):
    admin = "admin"
    docente = "docente"
    empleado = "empleado"
    dueno = "dueno"

# --------- Usuarios ---------
class Usuario(db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    correo = db.Column(db.String(100), unique=True, nullable=False)
    contrasena_hash = db.Column(db.String(255))  # por si luego usás login tradicional
    rol = db.Column(Enum(Rol), nullable=False, default=Rol.empleado)
    google_sub = db.Column(db.String(255), unique=True)

    # relaciones de conveniencia
    # empresas_donde_es_dueno -> relación 1:1 (usamos uselist=False en Empresa.dueno)
    def __repr__(self):
        return f"<Usuario {self.id} {self.nombre} ({self.rol.value})>"

# --------- Empresas ---------
class Empresa(db.Model):
    __tablename__ = "empresas"

    id_empresa = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nombre = db.Column(db.String(100), unique=True, nullable=False)
    descripcion = db.Column(db.Text)
    id_gerente = db.Column(db.Integer, ForeignKey("usuarios.id"), unique=True)

    # Dueño (objeto Usuario)
    dueno = relationship("Usuario", foreign_keys=[id_gerente], uselist=False)

    # Empleados afiliados (lista de EmpresaEmpleado)
    empleados = relationship(
        "EmpresaEmpleado",
        back_populates="empresa",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self):
        return f"<Empresa {self.id_empresa} {self.nombre}>"

# --------- Afiliaciones (empleado -> empresa) ---------
class EmpresaEmpleado(db.Model):
    __tablename__ = "empresa_empleados"

    # Clave primaria compuesta
    id_empresa = db.Column(db.Integer, ForeignKey("empresas.id_empresa", ondelete="CASCADE"), primary_key=True)
    id_usuario = db.Column(db.Integer, ForeignKey("usuarios.id"), primary_key=True, unique=True)
    # Nota: el UNIQUE en id_usuario garantiza que un empleado esté en una sola empresa

    empresa = relationship("Empresa", back_populates="empleados")
    usuario = relationship("Usuario")

    def __repr__(self):
        return f"<EmpresaEmpleado emp={self.id_empresa} usr={self.id_usuario}>"

# --- MODELOS CONTABLES MÍNIMOS ---

from sqlalchemy import Enum as SAEnum, UniqueConstraint
from datetime import date

class PlanCuenta(db.Model):
    __tablename__ = "plan_cuentas"

    id_cuenta = db.Column(db.Integer, primary_key=True, autoincrement=True)
    id_empresa = db.Column(db.Integer, db.ForeignKey("empresas.id_empresa"), nullable=False)
    cod_rubro = db.Column(db.String(50))
    rubro = db.Column(db.String(100))
    cod_subrubro = db.Column(db.String(50))
    subrubro = db.Column(db.String(100))
    cuenta = db.Column(db.String(100))

    empresa = relationship("Empresa")

    def __repr__(self):
        return f"<PlanCuenta {self.id_cuenta} {self.cuenta}>"

class Asiento(db.Model):
    __tablename__ = "asientos_diarios"

    id_asiento = db.Column(db.Integer, primary_key=True, autoincrement=True)
    id_empresa = db.Column(db.Integer, db.ForeignKey("empresas.id_empresa"), nullable=False)
    fecha = db.Column(db.Date, nullable=False, default=date.today)
    num_asiento = db.Column(db.Integer, nullable=False)  # correlativo por empresa
    doc_respaldatorio = db.Column(db.String(100))
    id_usuario = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    leyenda = db.Column(db.Text)

    __table_args__ = (
        UniqueConstraint("id_empresa", "num_asiento", name="uq_asiento_empresa"),
    )

    detalles = db.relationship(
        "DetalleAsiento",
        back_populates="asiento",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

class DetalleAsiento(db.Model):
    __tablename__ = "detalle_asiento"

    id_detalle = db.Column(db.Integer, primary_key=True, autoincrement=True)
    id_asiento = db.Column(
        db.Integer,
        db.ForeignKey("asientos_diarios.id_asiento", ondelete="CASCADE"),
        nullable=False,
    )
    # Ahora vinculada al plan de cuentas por empresa
    id_cuenta = db.Column(db.Integer, db.ForeignKey("plan_cuentas.id_cuenta"), nullable=False)

    tipo = db.Column(SAEnum("debe", "haber", name="tipo_asiento"), nullable=False)
    importe = db.Column(db.Numeric(12, 2), nullable=False)

    asiento = db.relationship("Asiento", back_populates="detalles")
    cuenta_ref = db.relationship("PlanCuenta")
