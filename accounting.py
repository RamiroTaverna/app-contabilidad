# accounting.py
from flask import Blueprint, render_template, request, redirect, url_for, g, abort, flash
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from models import db, Rol, Empresa, EmpresaEmpleado, Asiento, DetalleAsiento
from datetime import date
from decimal import Decimal

bp = Blueprint("accounting", __name__, url_prefix="/accounting")

# --- helpers auth ---

def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrap(*args, **kwargs):
        if not getattr(g, "user", None):
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return wrap

def _empresa_del_usuario():
    """ Devuelve id_empresa según rol:
        - dueño: su empresa
        - empleado: empresa afiliada
        - docente: None (debe filtrar por ?empresa=ID)
    """
    if g.user.rol == Rol.dueno:
        e = Empresa.query.filter_by(id_gerente=g.user.id).first()
        return e.id_empresa if e else None
    if g.user.rol == Rol.empleado:
        rel = EmpresaEmpleado.query.filter_by(id_usuario=g.user.id).first()
        return rel.id_empresa if rel else None
    return None  # docente

# --- routes ---

@bp.route("/journal", methods=["GET"], endpoint="journal_list")
@login_required
def journal_list():
    if g.user.rol == Rol.docente:
        # docente puede elegir empresa por querystring
        empresa_id = request.args.get("empresa", type=int)
        empresas = Empresa.query.order_by(Empresa.nombre).all()
        asientos = []
        if empresa_id:
            asientos = Asiento.query.filter_by(id_empresa=empresa_id).order_by(Asiento.fecha.desc(), Asiento.num_asiento.desc()).all()
        return render_template("accounting/journal_list.html", asientos=asientos, empresas=empresas, empresa_sel=empresa_id)

    empresa_id = _empresa_del_usuario()
    if not empresa_id:
        flash("No tienes empresa asociada.", "error")
        return render_template("accounting/journal_list.html", asientos=[])

    asientos = Asiento.query.filter_by(id_empresa=empresa_id).order_by(Asiento.fecha.desc(), Asiento.num_asiento.desc()).all()
    return render_template("accounting/journal_list.html", asientos=asientos, empresas=None, empresa_sel=empresa_id)

@bp.route("/journal/new", methods=["POST"], endpoint="journal_create")
@login_required
def journal_create():
    # empresa destino según rol
    if g.user.rol == Rol.docente:
        empresa_id = request.form.get("empresa", type=int)
        if not empresa_id:
            flash("Debes elegir una empresa.", "error")
            return redirect(url_for("accounting.journal_list"))
    else:
        empresa_id = _empresa_del_usuario()
        if not empresa_id:
            flash("No tienes empresa asociada.", "error")
            return redirect(url_for("accounting.journal_list"))

    # Datos del encabezado
    fecha = request.form.get("fecha") or date.today().isoformat()
    doc = (request.form.get("doc") or "").strip()
    leyenda = (request.form.get("leyenda") or "").strip()

    # Renglones
    cuentas = request.form.getlist("cuenta[]")
    tipos = request.form.getlist("tipo[]")
    importes_raw = request.form.getlist("importe[]")

    # Validación mínima
    if not cuentas or not tipos or not importes_raw or len(cuentas) != len(tipos) or len(cuentas) != len(importes_raw):
        flash("Renglones inválidos.", "error")
        return redirect(url_for("accounting.journal_list", empresa=empresa_id if g.user.rol == Rol.docente else None))

    # Sumas
    suma_debe = Decimal("0")
    suma_haber = Decimal("0")
    detalles = []
    for c, t, im in zip(cuentas, tipos, importes_raw):
        c = (c or "").strip()
        if not c:
            continue
        try:
            monto = Decimal(im)
        except Exception:
            flash("Importes inválidos.", "error")
            return redirect(url_for("accounting.journal_list", empresa=empresa_id if g.user.rol == Rol.docente else None))
        if monto <= 0:
            flash("Importes deben ser positivos.", "error")
            return redirect(url_for("accounting.journal_list", empresa=empresa_id if g.user.rol == Rol.docente else None))

        if t == "debe":
            suma_debe += monto
        elif t == "haber":
            suma_haber += monto
        else:
            flash("Tipo de renglón inválido.", "error")
            return redirect(url_for("accounting.journal_list", empresa=empresa_id if g.user.rol == Rol.docente else None))

        detalles.append((c, t, monto))

    if suma_debe == 0 or suma_haber == 0 or suma_debe != suma_haber:
        flash("La partida debe estar balanceada (Debe = Haber > 0).", "error")
        return redirect(url_for("accounting.journal_list", empresa=empresa_id if g.user.rol == Rol.docente else None))

    # Próximo número correlativo para esa empresa
    last_num = db.session.query(func.max(Asiento.num_asiento)).filter_by(id_empresa=empresa_id).scalar() or 0
    nuevo_num = last_num + 1

    try:
        a = Asiento(
            id_empresa=empresa_id,
            fecha=date.fromisoformat(fecha),
            num_asiento=nuevo_num,
            doc_respaldatorio=doc,
            id_usuario=g.user.id,
            leyenda=leyenda,
        )
        db.session.add(a)
        db.session.flush()  # para id_asiento

        for c, t, monto in detalles:
            db.session.add(DetalleAsiento(
                id_asiento=a.id_asiento,
                cuenta=c,
                tipo=t,
                importe=monto
            ))

        db.session.commit()
        flash(f"Asiento {nuevo_num} creado.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        flash("Error al guardar el asiento.", "error")

    return redirect(url_for("accounting.journal_list", empresa=empresa_id if g.user.rol == Rol.docente else None))
