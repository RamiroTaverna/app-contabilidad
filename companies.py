# companies.py
from flask import Blueprint, request, redirect, url_for, render_template, g, abort, flash
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from models import db, Empresa, Usuario, EmpresaEmpleado, Rol
from services.plan import clonar_plan_para_empresa  # asegúrate de tener este módulo

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

def require_docente_or_owner(f):
    from functools import wraps
    @wraps(f)
    def wrap(*args, **kwargs):
        if not getattr(g, "user", None):
            return redirect(url_for("auth.login", next=request.path))
        # docente ve todo
        if g.user.rol == Rol.docente:
            return f(*args, **kwargs)
        # dueño puede ver “ver más” solo de su empresa
        id_empresa = kwargs.get("id_empresa")
        e = db.session.get(Empresa, id_empresa)
        if e and e.id_gerente == g.user.id:
            return f(*args, **kwargs)
        abort(403)
    return wrap

def get_afiliacion(user_id: int):
    return EmpresaEmpleado.query.filter_by(id_usuario=user_id).first()

# ----------------- Vistas tipo “salas” -----------------
@bp.route("/", endpoint="list_companies")
def list_companies():
    """
    Grid de tarjetas (salas): nombre, ocupación, avatares, botón Entrar si aplica,
    y “Ver más” (docente/dueño).
    """
    user = getattr(g, "user", None)
    afiliado = get_afiliacion(user.id) if user and user.rol == Rol.empleado else None

    empresas = Empresa.query.order_by(Empresa.nombre.asc()).all()
    cards = []

    for e in empresas:
        empleados = [rel.usuario for rel in e.empleados]  # list[Usuario]
        total = 1 + len(empleados)                        # 1 dueño + empleados
        cupo_restante = max(0, 5 - len(empleados))

        puede_unirse = (
            user is not None
            and user.rol == Rol.empleado
            and afiliado is None
            and (e.id_gerente or -1) != user.id
            and cupo_restante > 0
        )

        # avatares: dueño + empleados (iniciales)
        integrantes = []
        if e.id_gerente:
            dueno = db.session.get(Usuario, e.id_gerente)
            if dueno:
                integrantes.append({"nombre": dueno.nombre, "rol": "dueño"})
        for u in empleados:
            integrantes.append({"nombre": u.nombre, "rol": "empleado"})

        cards.append(dict(
            id=e.id_empresa,
            nombre=e.nombre,
            total=total,
            lleno=(total >= 6),
            cupo=cupo_restante,
            integrantes=integrantes[:6],
            puede_unirse=puede_unirse,
            puede_ver_mas=(user and (user.rol == Rol.docente or e.id_gerente == user.id))
        ))

    return render_template("companies/list.html", cards=cards)

@bp.route("/<int:id_empresa>", endpoint="show_company")
@require_docente_or_owner
def show_company(id_empresa):
    """
    “Ver más”: docente (admin) o dueño ven los integrantes nominalmente.
    Empleados no acceden (según requisito).
    """
    e = db.session.get(Empresa, id_empresa)
    if not e:
        abort(404)
    dueno = db.session.get(Usuario, e.id_gerente) if e.id_gerente else None
    empleados = [rel.usuario for rel in e.empleados]
    return render_template("companies/show.html", empresa=e, dueno=dueno, empleados=empleados)

@bp.route("/mine")
@login_required
def my_company():
    """
    - Dueño: ve su empresa.
    - Empleado: ve la empresa a la que está afiliado.
    - Docente: ve listado de todas las empresas.
    """
    if g.user.rol == Rol.dueno:
        e = Empresa.query.filter_by(id_gerente=g.user.id).first()
        return render_template("companies/mine.html", empresa=e, rol="dueño")
    if g.user.rol == Rol.empleado:
        rel = get_afiliacion(g.user.id)
        e = db.session.get(Empresa, rel.id_empresa) if rel else None
        return render_template("companies/mine.html", empresa=e, rol="empleado")
    # docente
    empresas = Empresa.query.order_by(Empresa.nombre).all()
    return render_template("companies/mine.html", empresas=empresas, rol="docente")

# ----------------- Acciones: crear / unirse -----------------
@bp.route("/create", methods=["POST"])
@login_required
def create_company():
    """
    Crear empresa:
    - Empleado: no debe estar afiliado; si crea, pasa a dueño.
    - Dueño: no debe tener ya una empresa (id_gerente UNIQUE).
    Manejo de errores con flash() + toasts.
    """
    name = (request.form.get("nombre") or "").strip()
    if not name:
        flash("El nombre de la empresa es obligatorio.", "error")
        return redirect(url_for("companies.list_companies"))

    # Validaciones previas para evitar IntegrityError
    existe = Empresa.query.filter(func.lower(Empresa.nombre) == name.lower()).first()
    if existe:
        flash("Ya existe una empresa con ese nombre.", "error")
        return redirect(url_for("companies.list_companies"))

    if g.user.rol == Rol.empleado:
        if get_afiliacion(g.user.id):
            flash("No puedes crear una empresa si ya estás afiliado a otra.", "error")
            return redirect(url_for("companies.list_companies"))
        g.user.rol = Rol.dueno  # se convierte en dueño
    elif g.user.rol == Rol.dueno:
        if Empresa.query.filter_by(id_gerente=g.user.id).first():
            flash("Ya eres dueño de una empresa (solo 1 por usuario).", "error")
            return redirect(url_for("companies.list_companies"))

    e = Empresa(nombre=name, id_gerente=g.user.id)
    try:
        db.session.add(e)
        db.session.flush()  # asegura e.id_empresa para clonar plan

        # clonar plan de cuentas para esta empresa (si tu servicio lo requiere)
        clonar_plan_para_empresa(e.id_empresa)

        db.session.commit()
        flash("Empresa creada correctamente ✅", "success")
        return redirect(url_for("companies.my_company"))

    except IntegrityError as ex:
        db.session.rollback()
        msg = (str(ex.orig) or "").lower()
        if "unique" in msg and "id_gerente" in msg:
            flash("Ya eres dueño de una empresa. No puedes crear otra.", "error")
        elif "unique" in msg and "nombre" in msg:
            flash("El nombre de la empresa ya existe.", "error")
        else:
            flash("No se pudo crear la empresa por un conflicto de datos.", "error")
        return redirect(url_for("companies.list_companies"))

    except SQLAlchemyError:
        db.session.rollback()
        flash("Error interno al crear la empresa.", "error")
        return redirect(url_for("companies.list_companies"))

@bp.route("/join/<int:id_empresa>", methods=["POST"])
@login_required
def join_company(id_empresa):
    """
    Unirse a una empresa (solo empleados, 1 empresa por empleado, cupo 5).
    Manejo de errores con flash() + toasts.
    """
    if g.user.rol != Rol.empleado:
        flash("Solo empleados pueden unirse a una empresa.", "error")
        return redirect(url_for("companies.list_companies"))

    if get_afiliacion(g.user.id):
        flash("Ya estás afiliado a una empresa.", "error")
        return redirect(url_for("companies.list_companies"))

    e = db.session.get(Empresa, id_empresa)
    if not e:
        flash("La empresa no existe.", "error")
        return redirect(url_for("companies.list_companies"))

    # cupo: dueño + 5 empleados
    if len(e.empleados) >= 5:
        flash("La empresa no tiene cupos disponibles.", "error")
        return redirect(url_for("companies.list_companies"))

    if e.id_gerente == g.user.id:
        flash("No puedes unirte a tu propia empresa.", "error")
        return redirect(url_for("companies.list_companies"))

    try:
        db.session.add(EmpresaEmpleado(id_empresa=e.id_empresa, id_usuario=g.user.id))
        db.session.commit()
        flash("Te uniste correctamente a la empresa. 🎉", "success")
        return redirect(url_for("companies.my_company"))

    except IntegrityError as ex:
        db.session.rollback()
        msg = (str(ex.orig) or "").lower()
        if "unique" in msg and "id_usuario" in msg:
            flash("Cada empleado solo puede estar en una empresa.", "error")
        else:
            flash("No se pudo completar la unión por un conflicto de datos.", "error")
        return redirect(url_for("companies.list_companies"))

    except SQLAlchemyError:
        db.session.rollback()
        flash("Error interno al unirte a la empresa.", "error")
        return redirect(url_for("companies.list_companies"))
