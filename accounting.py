# accounting.py
from flask import Blueprint, render_template, request, redirect, url_for, g, abort, flash
from datetime import date
from sqlalchemy import func
from models import db, Asiento, DetalleAsiento, PlanCuenta, Empresa, Usuario, EmpresaEmpleado, Rol
from utils.scope import require_company_scope, get_user_company_id_or_none

bp = Blueprint("accounting", __name__, url_prefix="/accounting")

def next_num_asiento(id_empresa:int) -> int:
    last = db.session.query(func.max(Asiento.num_asiento)).filter_by(id_empresa=id_empresa).scalar()
    return (last or 0) + 1

@bp.route("/journal")
def journal_list():
    id_emp = get_user_company_id_or_none()
    q = Asiento.query
    if g.user and g.user.rol == Rol.docente:
        # docente ve todos (o podrías filtrar por ?empresa=)
        pass
    else:
        id_emp = require_company_scope()
        q = q.filter_by(id_empresa=id_emp)

    asientos = q.order_by(Asiento.fecha.desc(), Asiento.num_asiento.desc()).limit(100).all()
    return render_template("accounting/journal_list.html", asientos=asientos)

@bp.route("/journal/new", methods=["GET","POST"])
def journal_new():
    # dueños y empleados de una empresa; docente opcionalmente elegir empresa por form
    id_emp = get_user_company_id_or_none()
    if g.user.rol != Rol.docente and id_emp is None:
        abort(403)

    if request.method == "POST":
        # si docente, permitir seleccionar empresa por input hidden/select
        id_empresa = request.form.get("id_empresa") or id_emp
        if not id_empresa:
            abort(400, "Sin empresa.")
        id_empresa = int(id_empresa)

        fecha = request.form.get("fecha") or date.today().isoformat()
        leyenda = request.form.get("leyenda","").strip()
        filas = []  # [(id_cuenta, tipo, importe), ...]

        # Capturar filas dinámicas: inputs tipo id_cuenta_1, tipo_1, importe_1, etc.
        i = 1
        total_debe = 0
        total_haber = 0
        while True:
            cid = request.form.get(f"id_cuenta_{i}")
            tip = request.form.get(f"tipo_{i}")
            imp = request.form.get(f"importe_{i}")
            if not cid and not tip and not imp:
                break
            try:
                cid = int(cid)
                imp = float(imp)
            except Exception:
                abort(400, f"Fila {i} inválida")
            if tip not in ("debe","haber"):
                abort(400, f"Tipo inválido en fila {i}")
            if imp < 0:
                abort(400, f"Importe negativo en fila {i}")
            filas.append((cid, tip, imp))
            if tip == "debe": total_debe += imp
            else: total_haber += imp
            i += 1

        if len(filas) < 2:
            abort(400, "Necesitas al menos 2 renglones.")
        if round(total_debe,2) != round(total_haber,2):
            abort(400, "Partida doble inválida: debe != haber")

        # crear asiento + detalles en una transacción
        num = next_num_asiento(id_empresa)
        a = Asiento(
            id_empresa=id_empresa,
            fecha=fecha,
            num_asiento=num,
            leyenda=leyenda,
            id_usuario=g.user.id if g.user else None
        )
        db.session.add(a)
        db.session.flush()  # para obtener a.id_asiento

        for cid, tip, imp in filas:
            d = DetalleAsiento(
                id_asiento=a.id_asiento,
                id_cuenta=cid,
                tipo=tip,
                importe=imp
            )
            db.session.add(d)
        db.session.commit()
        return redirect(url_for("accounting.journal_list"))

    # GET: renderizar formulario
    # Cargar plan de cuentas de la empresa actual (o todas si docente)
    if g.user.rol == Rol.docente and not id_emp:
        # docente: opcionalmente filtrar por empresa en la UI
        cuentas = PlanCuenta.query.order_by(PlanCuenta.id_empresa, PlanCuenta.cuenta).limit(500).all()
    else:
        cuentas = PlanCuenta.query.filter_by(id_empresa=id_emp).order_by(PlanCuenta.cuenta).all()

    return render_template("accounting/journal_new.html", cuentas=cuentas, id_empresa=id_emp)

@bp.route("/mayor")
def mayor_view():
    id_emp = get_user_company_id_or_none()
    if g.user and g.user.rol != Rol.docente:
        id_emp = require_company_scope()

    # Cuentas de esta empresa
    cuentas = PlanCuenta.query.filter_by(id_empresa=id_emp).order_by(PlanCuenta.cuenta).all() if id_emp else []
    data = []
    for c in cuentas:
        debe = db.session.query(func.coalesce(func.sum(DetalleAsiento.importe),0)).\
            join(Asiento, DetalleAsiento.id_asiento==Asiento.id_asiento).\
            filter(Asiento.id_empresa==id_emp, DetalleAsiento.id_cuenta==c.id_cuenta, DetalleAsiento.tipo=="debe").scalar()
        haber = db.session.query(func.coalesce(func.sum(DetalleAsiento.importe),0)).\
            join(Asiento, DetalleAsiento.id_asiento==Asiento.id_asiento).\
            filter(Asiento.id_empresa==id_emp, DetalleAsiento.id_cuenta==c.id_cuenta, DetalleAsiento.tipo=="haber").scalar()
        saldo = float(debe) - float(haber)
        data.append(dict(cuenta=c.cuenta, rubro=c.rubro, debe=float(debe), haber=float(haber), saldo=saldo))
    return render_template("accounting/mayor.html", filas=data)
