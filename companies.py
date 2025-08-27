from flask import Blueprint, request, redirect, url_for, render_template, g, abort
from sqlalchemy import func
from models import db, Empresa, Usuario, EmpresaEmpleado, Rol
from services.plan import clonar_plan_para_empresa  # <-- IMPORTANTE

bp = Blueprint("companies", __name__, url_prefix="/companies")

# ----------------- Helpers de auth/roles -----------------
def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrap(*args, **kwargs):
        if not getattr(g, "user", None):
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return wrap

def require_role(*roles):
    def deco(f):
        from functools import wraps
        @wraps(f)
        def wrap(*args, **kwargs):
            if not getattr(g, "user", None) or g.user.rol.value not in roles:
                abort(403)
            return f(*args, **kwargs)
        return wrap
    return deco

def _empleado_afiliado(user_id: int) -> EmpresaEmpleado | None:
    return EmpresaEmpleado.query.filter_by(id_usuario=user_id).first()

# ----------------- Rutas -----------------
@bp.route("/", endpoint="list_companies")
def list_companies():
    """
    Listado público de empresas:
    - Cualquiera puede ver nombre y conteo.
    - Si hay un usuario logueado con rol 'empleado' y no está afiliado, indicamos si puede unirse.
    """
    empresas = Empresa.query.order_by(Empresa.nombre).all()
    vista = []
    user = getattr(g, "user", None)
    ya_afiliado = None
    if user and user.rol == Rol.empleado:
        ya_afiliado = _empleado_afiliado(user.id)

    for e in empresas:
        empleados_count = len(e.empleados)  # relación Empresa.empleados -> EmpresaEmpleado
        total = 1 + empleados_count         # 1 dueño + empleados
        cupo_emps_restante = max(0, 5 - empleados_count)

        puede_unirse = False
        if user and user.rol == Rol.empleado:
            puede_unirse = (
                (ya_afiliado is None) and
                (user.id != (e.id_gerente or -1)) and
                (cupo_emps_restante > 0)
            )

        vista.append(dict(
            id=e.id_empresa,
            nombre=e.nombre,
            total=total,
            cupo=cupo_emps_restante,
            puede_unirse=puede_unirse
        ))

    return render_template("companies/list.html", empresas=vista, user=user)

@bp.route("/mine")
@login_required
def my_company():
    """
    - Dueño: ve su empresa.
    - Empleado: ve la empresa a la que está afiliado.
    - Docente: ve listado de todas las empresas (sin usuarios si no querés).
    """
    if g.user.rol == Rol.dueno:
        e = Empresa.query.filter_by(id_gerente=g.user.id).first()
        return render_template("companies/mine.html", empresa=e, rol="dueño", user=g.user)

    if g.user.rol == Rol.empleado:
        rel = _empleado_afiliado(g.user.id)
        e = Empresa.query.get(rel.id_empresa) if rel else None
        return render_template("companies/mine.html", empresa=e, rol="empleado", user=g.user)

    # docente
    empresas = Empresa.query.order_by(Empresa.nombre).all()
    return render_template("companies/mine.html", empresas=empresas, rol="docente", user=g.user)

@bp.route("/create", methods=["POST"])
@login_required
def create_company():
    """
    Crear empresa:
    - Empleado: no debe estar afiliado, se convierte en dueño.
    - Dueño: no debe tener ya una empresa.
    """
    name = (request.form.get("nombre") or "").strip()
    if not name:
        abort(400, "Nombre requerido")

    # unicidad case-insensitive (por si colación no es CI)
    existe = Empresa.query.filter(func.lower(Empresa.nombre) == name.lower()).first()
    if existe:
        abort(400, "Ya existe una empresa con ese nombre.")

    if g.user.rol == Rol.empleado:
        if _empleado_afiliado(g.user.id):
            abort(400, "No puedes crear empresa estando afiliado.")
        g.user.rol = Rol.dueno  # pasa a dueño

    elif g.user.rol == Rol.dueno:
        if Empresa.query.filter_by(id_gerente=g.user.id).first():
            abort(400, "Ya eres dueño de una empresa.")

    e = Empresa(nombre=name, id_gerente=g.user.id)
    db.session.add(e)
    db.session.flush()  # para tener e.id_empresa

    # clonar plan de cuentas para esta empresa
    clonar_plan_para_empresa(e.id_empresa)

    db.session.commit()
    return redirect(url_for("companies.my_company"))

@bp.route("/join/<int:id_empresa>", methods=["POST"])
@login_required
def join_company(id_empresa):
    """
    Unirse a una empresa (solo empleados, 1 empresa por empleado, cupo 5).
    """
    if g.user.rol != Rol.empleado:
        abort(400, "Solo empleados pueden unirse.")

    if _empleado_afiliado(g.user.id):
        abort(400, "Ya estás afiliado a una empresa.")

    e = Empresa.query.get_or_404(id_empresa)

    # cupo: dueño + 5 empleados
    if len(e.empleados) >= 5:
        abort(400, "La empresa no tiene cupos disponibles.")

    if e.id_gerente and e.id_gerente == g.user.id:
        abort(400, "No puedes unirte a tu propia empresa como empleado.")

    rel = EmpresaEmpleado(id_empresa=e.id_empresa, id_usuario=g.user.id)
    db.session.add(rel)
    db.session.commit()
    return redirect(url_for("companies.my_company"))
