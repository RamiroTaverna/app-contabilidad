# accounting.py
from flask import Blueprint, render_template, request, redirect, url_for, g, abort, flash, jsonify
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from models import db, Rol, Empresa, EmpresaEmpleado, Asiento, DetalleAsiento, PlanCuenta, ChangeLog
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
    # Reemplazo total: redirige a la nueva UI integrada
    empresa_id = request.args.get("empresa", type=int)
    if empresa_id:
        return redirect(url_for("accounting.mini", empresa=empresa_id))
    return redirect(url_for("accounting.mini"))

@bp.route("/mini", methods=["GET"], endpoint="mini")
@login_required
def mini():
    empresas = None
    empresa_sel = None
    if g.user.rol == Rol.docente:
        empresas = Empresa.query.order_by(Empresa.nombre).all()
        empresa_sel = request.args.get("empresa", type=int)
    else:
        empresa_sel = _empresa_del_usuario()
    return render_template("accounting/mini_app.html", empresas=empresas, empresa_sel=empresa_sel)

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
    cuentas_ids = request.form.getlist("cuenta_id[]")
    tipos = request.form.getlist("tipo[]")
    importes_raw = request.form.getlist("importe[]")

    # Validación mínima
    if not cuentas_ids or not tipos or not importes_raw or len(cuentas_ids) != len(tipos) or len(cuentas_ids) != len(importes_raw):
        flash("Renglones inválidos.", "error")
        return redirect(url_for("accounting.journal_list", empresa=empresa_id if g.user.rol == Rol.docente else None))

# =====================
#      API (REST)
# =====================

def _empresa_actual_from_request():
    """Resuelve id_empresa según el rol y request actual, sin cambiar el esquema.
    - docente: admite ?empresa=ID (requerido para operaciones de lectura/escritura)
    - dueño/empleado: según afiliación
    """
    if not getattr(g, "user", None):
        abort(401)
    if g.user.rol == Rol.docente:
        emp = request.args.get("empresa", type=int)
        if emp:
            return emp
        payload = request.get_json(silent=True) if request.is_json else None
        emp = (payload or {}).get("empresa")
        if not emp:
            abort(400, description="Se requiere parametro empresa para rol docente")
        return emp
    emp = _empresa_del_usuario()
    if not emp:
        abort(400, description="Usuario sin empresa asociada")
    return emp

def _ensure_owner_access(empresa_id: int):
    """Solo el dueño (o admin) de la empresa puede mutar sus datos contables."""
    if not getattr(g, "user", None):
        abort(401)
    if g.user.rol == Rol.admin:
        return
    if g.user.rol != Rol.dueno:
        abort(403, description="Solo el dueño puede modificar la contabilidad.")
    empresa = Empresa.query.filter_by(id_gerente=g.user.id).first()
    if not empresa or empresa.id_empresa != empresa_id:
        abort(403, description="Solo el dueño de la empresa puede realizar esta acción.")

def _detalle_to_dict(d: DetalleAsiento):
    return dict(
        id_detalle=d.id_detalle,
        id_cuenta=d.id_cuenta,
        cuenta=d.cuenta_ref.cuenta if d.cuenta_ref else None,
        rubro=(d.cuenta_ref.rubro if d.cuenta_ref else None),
        subrubro=(d.cuenta_ref.subrubro if d.cuenta_ref else None),
        tipo=d.tipo,
        importe=float(d.importe),
    )

def _asiento_to_dict(a: Asiento):
    return dict(
        id_asiento=a.id_asiento,
        id_empresa=a.id_empresa,
        fecha=a.fecha.isoformat(),
        num_asiento=a.num_asiento,
        doc_respaldatorio=a.doc_respaldatorio,
        id_usuario=a.id_usuario,
        leyenda=a.leyenda,
        detalles=[_detalle_to_dict(d) for d in a.detalles],
    )

def _asignar_codigos_rubro_subrubro(rubro: str, subrubro: str) -> tuple:
    """Asigna automáticamente los códigos de rubro y subrubro según el tipo"""
    rubro_upper = (rubro or "").strip().upper()
    subrubro_upper = (subrubro or "").strip().upper()
    
    # Mapeo de rubros a códigos
    codigo_rubro = None
    codigo_subrubro = None
    
    if "ACTIVO" in rubro_upper:
        codigo_rubro = "1"
        if "CORRIENTE" in subrubro_upper and "NO" not in subrubro_upper:
            codigo_subrubro = "1.1"
        elif "NO CORRIENTE" in subrubro_upper:
            codigo_subrubro = "1.2"
        elif "OTROS" in subrubro_upper:
            codigo_subrubro = "1.3"
    elif "PASIVO" in rubro_upper:
        codigo_rubro = "2"
        if "CORRIENTE" in subrubro_upper and "NO" not in subrubro_upper:
            codigo_subrubro = "2.1"
        elif "NO CORRIENTE" in subrubro_upper:
            codigo_subrubro = "2.2"
        elif "OTROS" in subrubro_upper:
            codigo_subrubro = "2.3"
    elif "PATRIMONIO" in rubro_upper:
        codigo_rubro = "3"
        if "CAPITAL" in subrubro_upper:
            codigo_subrubro = "3.1"
        elif "RESULTADOS ACUMULADOS" in subrubro_upper:
            codigo_subrubro = "3.2"
        elif "RESULTADOS DEL EJERCICIO" in subrubro_upper or "EJERCICIO" in subrubro_upper:
            codigo_subrubro = "3.3"
    elif "INGRESOS" in rubro_upper or "VENTAS" in rubro_upper:
        codigo_rubro = "4"
        if "INGRESOS" in subrubro_upper or "VENTAS" in subrubro_upper:
            codigo_subrubro = "4.1"
        elif "OTROS" in subrubro_upper:
            codigo_subrubro = "4.2"
    elif "EGRESOS" in rubro_upper or "GASTOS" in rubro_upper or "COSTOS" in rubro_upper:
        codigo_rubro = "5"
        if "EGRESOS" in subrubro_upper or "COSTOS" in subrubro_upper or "COSTO" in subrubro_upper:
            codigo_subrubro = "5.1"
        elif "ADMINISTRACIÓN" in subrubro_upper or "ADMINISTRACION" in subrubro_upper:
            codigo_subrubro = "5.2"
        elif "COMERCIALIZACIÓN" in subrubro_upper or "COMERCIALIZACION" in subrubro_upper:
            codigo_subrubro = "5.3"
        elif "FINANCIEROS" in subrubro_upper:
            codigo_subrubro = "5.4"
        elif "OTROS" in subrubro_upper:
            codigo_subrubro = "5.5"
    
    return (codigo_rubro, codigo_subrubro)

def _normal_side_for(c: PlanCuenta) -> str:
    """Heurística de naturaleza del saldo sin cambiar el esquema.
    D: Activo/Gasto; H: Pasivo/Patrimonio/Ingreso
    """
    txt = " ".join(filter(None, [c.rubro, c.subrubro])).lower()
    if any(k in txt for k in ["activo", "caja", "banco", "bancos", "clientes", "inventario", "existencias"]):
        return "D"
    if any(k in txt for k in ["pasivo", "proveedores", "deudas", "obligaciones"]):
        return "H"
    if any(k in txt for k in ["patrimonio", "capital"]):
        return "H"
    if any(k in txt for k in ["ingreso", "ventas", "ingresos"]):
        return "H"
    if any(k in txt for k in ["gasto", "costos", "costo"]):
        return "D"
    # por defecto
    return "D"

@bp.get("/api/cuentas")
@login_required
def api_cuentas_list():
    empresa_id = _empresa_actual_from_request()
    cuentas = PlanCuenta.query.filter_by(id_empresa=empresa_id).order_by(PlanCuenta.cuenta.asc()).all()
    data = [dict(
        id_cuenta=c.id_cuenta,
        cuenta=c.cuenta,
        rubro=c.rubro,
        subrubro=c.subrubro,
        cod_rubro=c.cod_rubro,
        cod_subrubro=c.cod_subrubro,
        normal=_normal_side_for(c),
    ) for c in cuentas]
    return jsonify(data)

@bp.post("/api/cuentas")
@login_required
def api_cuentas_create():
    if not request.is_json:
        abort(400, description="JSON requerido")
    payload = request.get_json()
    empresa_id = _empresa_actual_from_request()
    _ensure_owner_access(empresa_id)
    # Datos de entrada: codigo (de la cuenta), nombre, tipo (Activo/Pasivo/Patrimonio/Ingreso/Gasto)
    codigo_cuenta = (payload.get("codigo") or "").strip().upper()
    nombre = (payload.get("nombre") or "").strip().upper()
    tipo = payload.get("tipo", "").strip()
    subrubro_req = (payload.get("subrubro") or "").strip()
    if not nombre:
        abort(400, description="Nombre requerido")
    # Mapear tipo a rubro para soportar heurística
    tipo_norm = tipo.lower()
    rubro = None
    # Mapeo desde nuevos dropdowns
    if tipo_norm == "activo":
        rubro = "Activo"
    elif tipo_norm == "pasivo":
        rubro = "Pasivo"
    elif tipo_norm in ("patrimonio neto", "patrimonio"):
        rubro = "Patrimonio"
    elif tipo_norm in ("cuentas de resultado",):
        # Diferenciar ingresos vs gastos por subrubro seleccionado
        sr = subrubro_req.lower()
        if sr.startswith("ingresos") or "ventas" in sr:
            rubro = "Ingresos"
        else:
            rubro = "Gastos"
    elif tipo_norm in ("ingreso","ingresos"):
        rubro = "Ingresos"
    elif tipo_norm in ("gasto","gastos"):
        rubro = "Gastos"
    
    # Asignar automáticamente códigos de rubro y subrubro
    cod_rubro_auto, cod_subrubro_auto = _asignar_codigos_rubro_subrubro(rubro, subrubro_req)
    
    # Crear registro: codigo_cuenta va en cod_rubro (es el código de la cuenta, no del rubro)
    # Los códigos automáticos de rubro/subrubro se guardan en campos separados si es necesario
    # Por ahora, cod_rubro guarda el código de la cuenta y cod_subrubro el código automático del subrubro
    pc = PlanCuenta(
        id_empresa=empresa_id,
        cuenta=nombre,
        cod_rubro=codigo_cuenta or None,  # Código de la cuenta (ej: 1101)
        rubro=rubro,
        cod_subrubro=cod_subrubro_auto,  # Código automático del subrubro (ej: 1.1)
        subrubro=subrubro_req or None,
    )
    try:
        db.session.add(pc)
        db.session.flush()
        # Auditoría
        db.session.add(ChangeLog(
            entidad="cuenta",
            id_entidad=pc.id_cuenta,
            accion="create",
            id_usuario=getattr(g, 'user', None).id if getattr(g, 'user', None) else None,
            datos=f"{{\"codigo\":\"{codigo_cuenta}\",\"nombre\":\"{nombre}\",\"tipo\":\"{tipo}\"}}",
        ))
        db.session.commit()
        return jsonify(dict(
            id_cuenta=pc.id_cuenta,
            cuenta=pc.cuenta,
            cod_rubro=pc.cod_rubro,
            rubro=pc.rubro,
            subrubro=pc.subrubro,
            normal=_normal_side_for(pc),
        )), 201
    except SQLAlchemyError:
        db.session.rollback()
        abort(500, description="Error al crear la cuenta")

@bp.delete("/api/cuentas/<int:cuenta_id>")
@login_required
def api_cuentas_delete(cuenta_id: int):
    empresa_id = _empresa_actual_from_request()
    _ensure_owner_access(empresa_id)
    cuenta = PlanCuenta.query.filter_by(id_cuenta=cuenta_id, id_empresa=empresa_id).first()
    if not cuenta:
        abort(404, description="Cuenta no encontrada")
    
    # Verificar si la cuenta está siendo usada en algún asiento
    tiene_detalles = DetalleAsiento.query.filter_by(id_cuenta=cuenta_id).first()
    if tiene_detalles:
        abort(400, description="No se puede eliminar una cuenta que está siendo usada en asientos")
    
    try:
        nombre_cuenta = cuenta.cuenta
        db.session.delete(cuenta)
        db.session.add(ChangeLog(
            entidad="cuenta",
            id_entidad=cuenta_id,
            accion="delete",
            id_usuario=g.user.id,
            datos=f'{{"cuenta":"{nombre_cuenta}"}}',
        ))
        db.session.commit()
        return jsonify({"status": "deleted"})
    except SQLAlchemyError:
        db.session.rollback()
        abort(500, description="Error al eliminar la cuenta")

@bp.get("/api/asientos")
@login_required
def api_asientos_list():
    empresa_id = _empresa_actual_from_request()
    q = Asiento.query.filter_by(id_empresa=empresa_id)
    # filtros opcionales de fecha
    desde_s = request.args.get("desde")
    hasta_s = request.args.get("hasta")
    from datetime import date as _date
    try:
        if desde_s:
            q = q.filter(Asiento.fecha >= _date.fromisoformat(desde_s))
        if hasta_s:
            q = q.filter(Asiento.fecha <= _date.fromisoformat(hasta_s))
    except Exception:
        abort(400, description="Formato de fecha inválido. Use YYYY-MM-DD")
    asientos = q.order_by(Asiento.fecha.desc(), Asiento.num_asiento.desc()).all()
    return jsonify([_asiento_to_dict(a) for a in asientos])

@bp.post("/api/asientos")
@login_required
def api_asientos_create():
    if not request.is_json:
        abort(400, description="JSON requerido")
    payload = request.get_json()
    empresa_id = _empresa_actual_from_request()
    _ensure_owner_access(empresa_id)
    from datetime import date
    try:
        fecha = date.fromisoformat(payload.get("fecha") or date.today().isoformat())
    except Exception:
        abort(400, description="Fecha inválida")
    doc = (payload.get("doc") or "").strip()
    leyenda = (payload.get("leyenda") or "").strip()
    renglones = payload.get("renglones") or []
    if len(renglones) < 2:
        abort(400, description="Debe haber al menos dos renglones")
    suma_debe = Decimal("0")
    suma_haber = Decimal("0")
    detalles = []
    cuenta_ids = set()
    for r in renglones:
        c_id = r.get("id_cuenta")
        t = r.get("tipo")
        im_raw = r.get("importe")
        try:
            c_id_int = int(c_id)
        except Exception:
            continue
        if t not in ("debe", "haber"):
            abort(400, description="Tipo inválido")
        try:
            monto = Decimal(str(im_raw))
        except Exception:
            abort(400, description="Importe inválido")
        if monto <= 0:
            abort(400, description="Importe debe ser positivo")
        if t == "debe":
            suma_debe += monto
        else:
            suma_haber += monto
        detalles.append((c_id_int, t, monto))
        cuenta_ids.add(c_id_int)
    if suma_debe == 0 or suma_haber == 0 or suma_debe != suma_haber:
        abort(400, description="La partida debe estar balanceada (Debe = Haber > 0)")
    if cuenta_ids:
        cuentas = PlanCuenta.query.filter(PlanCuenta.id_cuenta.in_(cuenta_ids)).all()
        cuentas_map = {c.id_cuenta: c for c in cuentas}
        if len(cuentas_map) != len(cuenta_ids):
            abort(400, description="Alguna cuenta no existe.")
        for c in cuentas_map.values():
            if c.id_empresa != empresa_id:
                abort(400, description="Solo se pueden usar cuentas de la empresa seleccionada.")
    # correlativo por empresa
    last_num = db.session.query(func.max(Asiento.num_asiento)).filter_by(id_empresa=empresa_id).scalar() or 0
    nuevo_num = last_num + 1
    try:
        a = Asiento(
            id_empresa=empresa_id,
            fecha=fecha,
            num_asiento=nuevo_num,
            doc_respaldatorio=doc,
            id_usuario=g.user.id,
            leyenda=leyenda,
        )
        db.session.add(a)
        db.session.flush()
        for c_id_int, t, monto in detalles:
            db.session.add(DetalleAsiento(
                id_asiento=a.id_asiento,
                id_cuenta=c_id_int,
                tipo=t,
                importe=monto,
            ))
        # Auditoría
        db.session.add(ChangeLog(
            entidad="asiento",
            id_entidad=a.id_asiento,
            accion="create",
            id_usuario=g.user.id,
            datos=f"{{\"fecha\":\"{fecha.isoformat()}\",\"num\":{nuevo_num},\"renglones\":{len(detalles)}}}"
        ))
        db.session.commit()
        return jsonify(_asiento_to_dict(a)), 201
    except SQLAlchemyError as e:
        db.session.rollback()
        abort(500, description="Error al guardar el asiento")

@bp.delete("/api/asientos/<int:asiento_id>")
@login_required
def api_asientos_delete(asiento_id: int):
    empresa_id = _empresa_actual_from_request()
    _ensure_owner_access(empresa_id)
    asiento = Asiento.query.filter_by(id_asiento=asiento_id, id_empresa=empresa_id).first()
    if not asiento:
        abort(404, description="Asiento no encontrado")
    try:
        db.session.delete(asiento)
        db.session.add(ChangeLog(
            entidad="asiento",
            id_entidad=asiento_id,
            accion="delete",
            id_usuario=g.user.id,
            datos=f'{{"num":{asiento.num_asiento}}}',
        ))
        db.session.commit()
        return jsonify({"status": "deleted"})
    except SQLAlchemyError:
        db.session.rollback()
        abort(500, description="Error al eliminar el asiento")

@bp.get("/api/mayor")
@login_required
def api_mayor():
    empresa_id = _empresa_actual_from_request()
    cuenta_id = request.args.get("cuenta", type=int)
    if not cuenta_id:
        abort(400, description="Parámetro cuenta requerido")
    cuenta = db.session.get(PlanCuenta, cuenta_id)
    if not cuenta or cuenta.id_empresa != empresa_id:
        abort(404, description="Cuenta no encontrada")
    nb = _normal_side_for(cuenta)
    # Traer detalles de la cuenta por orden
    q = (
        db.session.query(DetalleAsiento, Asiento)
        .join(Asiento, DetalleAsiento.id_asiento == Asiento.id_asiento)
        .filter(Asiento.id_empresa == empresa_id, DetalleAsiento.id_cuenta == cuenta_id)
    )
    # Filtros opcionales de fecha
    desde_s = request.args.get("desde")
    hasta_s = request.args.get("hasta")
    from datetime import date as _date
    try:
        if desde_s:
            q = q.filter(Asiento.fecha >= _date.fromisoformat(desde_s))
        if hasta_s:
            q = q.filter(Asiento.fecha <= _date.fromisoformat(hasta_s))
    except Exception:
        abort(400, description="Formato de fecha inválido. Use YYYY-MM-DD")
    dets = q.order_by(Asiento.fecha.asc(), Asiento.num_asiento.asc(), DetalleAsiento.id_detalle.asc()).all()
    saldo = Decimal("0")
    movs = []
    for d, a in dets:
        if d.tipo == "debe":
            saldo += (d.importe if nb == "D" else -d.importe)
        else:
            saldo += (d.importe if nb == "H" else -d.importe)
        movs.append(dict(
            fecha=a.fecha.isoformat(),
            concepto=a.leyenda or "",
            debe=float(d.importe) if d.tipo == "debe" else 0.0,
            haber=float(d.importe) if d.tipo == "haber" else 0.0,
            saldo=float(saldo),
        ))
    side = "Deudor" if nb == "D" else "Acreedor"
    return jsonify(dict(
        cuenta=dict(id_cuenta=cuenta.id_cuenta, nombre=cuenta.cuenta),
        normal=nb,
        saldo=float(saldo),
        side=side,
        movimientos=movs,
    ))

@bp.get("/api/balance")
@login_required
def api_balance():
    empresa_id = _empresa_actual_from_request()
    cuentas = PlanCuenta.query.filter_by(id_empresa=empresa_id).all()
    # Precalcular saldos por cuenta
    saldos = {c.id_cuenta: Decimal("0") for c in cuentas}
    nb_map = {c.id_cuenta: _normal_side_for(c) for c in cuentas}
    q = (
        db.session.query(DetalleAsiento, Asiento)
        .join(Asiento, DetalleAsiento.id_asiento == Asiento.id_asiento)
        .filter(Asiento.id_empresa == empresa_id)
    )
    # filtros de fecha opcionales
    desde_s = request.args.get("desde")
    hasta_s = request.args.get("hasta")
    from datetime import date as _date
    try:
        if desde_s:
            q = q.filter(Asiento.fecha >= _date.fromisoformat(desde_s))
        if hasta_s:
            q = q.filter(Asiento.fecha <= _date.fromisoformat(hasta_s))
    except Exception:
        abort(400, description="Formato de fecha inválido. Use YYYY-MM-DD")
    dets = q.all()
    for d, a in dets:
        nb = nb_map.get(d.id_cuenta, "D")
        if d.tipo == "debe":
            saldos[d.id_cuenta] += (d.importe if nb == "D" else -d.importe)
        else:
            saldos[d.id_cuenta] += (d.importe if nb == "H" else -d.importe)
    rows = []
    td = Decimal("0"); th = Decimal("0")
    for c in sorted(cuentas, key=lambda x: (x.cuenta or "")):
        nb = nb_map[c.id_cuenta]
        saldo = saldos[c.id_cuenta]
        deudor = saldo if (nb == "D" and saldo >= 0) or (nb == "H" and saldo < 0) else Decimal("0")
        acreedor = saldo if (nb == "H" and saldo >= 0) or (nb == "D" and saldo < 0) else Decimal("0")
        if deudor < 0:
            deudor = -deudor
        if acreedor < 0:
            acreedor = -acreedor
        td += deudor
        th += acreedor
        rows.append(dict(
            id_cuenta=c.id_cuenta,
            cod_rubro=c.cod_rubro,
            cuenta=c.cuenta,
            deudor=float(deudor),
            acreedor=float(acreedor),
        ))
    return jsonify(dict(rows=rows, total_debe=float(td), total_haber=float(th), cuadra=abs(td - th) < Decimal("0.005")))

@bp.get("/api/estado-patrimonial")
@login_required
def api_estado_patrimonial():
    """Endpoint para estado de situación patrimonial agrupado por rubro y subrubro"""
    empresa_id = _empresa_actual_from_request()
    cuentas = PlanCuenta.query.filter_by(id_empresa=empresa_id).all()
    
    # Precalcular saldos por cuenta
    saldos = {c.id_cuenta: Decimal("0") for c in cuentas}
    nb_map = {c.id_cuenta: _normal_side_for(c) for c in cuentas}
    
    q = (
        db.session.query(DetalleAsiento, Asiento)
        .join(Asiento, DetalleAsiento.id_asiento == Asiento.id_asiento)
        .filter(Asiento.id_empresa == empresa_id)
    )
    
    # Filtros de fecha opcionales
    desde_s = request.args.get("desde")
    hasta_s = request.args.get("hasta")
    from datetime import date as _date
    try:
        if desde_s:
            q = q.filter(Asiento.fecha >= _date.fromisoformat(desde_s))
        if hasta_s:
            q = q.filter(Asiento.fecha <= _date.fromisoformat(hasta_s))
    except Exception:
        abort(400, description="Formato de fecha inválido. Use YYYY-MM-DD")
    
    dets = q.all()
    for d, a in dets:
        nb = nb_map.get(d.id_cuenta, "D")
        if d.tipo == "debe":
            saldos[d.id_cuenta] += (d.importe if nb == "D" else -d.importe)
        else:
            saldos[d.id_cuenta] += (d.importe if nb == "H" else -d.importe)
    
    # Agrupar por rubro y subrubro (normalizando a mayúsculas para comparación)
    grupos = {}  # clave: (rubro_upper, subrubro_upper) -> {cod_rubro, rubro, cod_subrubro, subrubro, importe}
    
    for c in cuentas:
        if not c.rubro and not c.subrubro:
            continue
        
        # Normalizar a mayúsculas para agrupación y comparación
        rubro_upper = (c.rubro or "").strip().upper()
        subrubro_upper = (c.subrubro or "").strip().upper()
        
        # Obtener valores originales (preservando mayúsculas originales si existen)
        rubro_original = c.rubro or ""
        subrubro_original = c.subrubro or ""
        
        # Calcular códigos automáticos del rubro y subrubro
        cod_rubro_auto, cod_subrubro_auto = _asignar_codigos_rubro_subrubro(rubro_original, subrubro_original)
        
        # Calcular saldo normalizado (valor absoluto para el importe)
        nb = nb_map[c.id_cuenta]
        saldo = saldos[c.id_cuenta]
        # El saldo ya está normalizado según la naturaleza de la cuenta
        # Tomamos el valor absoluto para el importe
        importe = abs(saldo)
        
        # Clave de agrupación (usando mayúsculas para comparación)
        clave = (rubro_upper, subrubro_upper)
        
        if clave not in grupos:
            grupos[clave] = {
                "cod_rubro": cod_rubro_auto or "",
                "rubro": rubro_original,
                "cod_subrubro": cod_subrubro_auto or "",
                "subrubro": subrubro_original,
                "importe": Decimal("0")
            }
        
        grupos[clave]["importe"] += importe
    
    # Convertir a lista y ordenar
    rows = []
    for (rubro_upper, subrubro_upper), datos in grupos.items():
        rows.append({
            "cod_rubro": datos["cod_rubro"],
            "rubro": datos["rubro"],
            "cod_subrubro": datos["cod_subrubro"],
            "subrubro": datos["subrubro"],
            "importe": float(datos["importe"])
        })
    
    # Ordenar por rubro y subrubro (usando mayúsculas para consistencia en la comparación)
    rows.sort(key=lambda x: (
        (x["rubro"] or "").upper(),
        (x["subrubro"] or "").upper()
    ))
    
    return jsonify(dict(rows=rows))

@bp.get("/api/estados")
@login_required
def api_estados():
    empresa_id = _empresa_actual_from_request()
    cuentas = PlanCuenta.query.filter_by(id_empresa=empresa_id).all()
    nb_map = {c.id_cuenta: _normal_side_for(c) for c in cuentas}
    txt_map = {c.id_cuenta: (" ".join(filter(None, [c.rubro, c.subrubro])).lower()) for c in cuentas}
    saldos = {c.id_cuenta: Decimal("0") for c in cuentas}
    q = (
        db.session.query(DetalleAsiento, Asiento)
        .join(Asiento, DetalleAsiento.id_asiento == Asiento.id_asiento)
        .filter(Asiento.id_empresa == empresa_id)
    )
    desde_s = request.args.get("desde")
    hasta_s = request.args.get("hasta")
    from datetime import date as _date
    try:
        if desde_s:
            q = q.filter(Asiento.fecha >= _date.fromisoformat(desde_s))
        if hasta_s:
            q = q.filter(Asiento.fecha <= _date.fromisoformat(hasta_s))
    except Exception:
        abort(400, description="Formato de fecha inválido. Use YYYY-MM-DD")
    dets = q.all()
    for d, a in dets:
        nb = nb_map.get(d.id_cuenta, "D")
        if d.tipo == "debe":
            saldos[d.id_cuenta] += (d.importe if nb == "D" else -d.importe)
        else:
            saldos[d.id_cuenta] += (d.importe if nb == "H" else -d.importe)
    # Clasificación heurística
    def is_ingreso(txt):
        return any(k in txt for k in ["ingreso", "ventas", "ingresos"])
    def is_gasto(txt):
        return any(k in txt for k in ["gasto", "costos", "costo"])
    def is_activo(txt):
        return any(k in txt for k in ["activo", "banco", "bancos", "caja", "clientes", "inventario"])
    def is_pasivo(txt):
        return any(k in txt for k in ["pasivo", "proveedores", "deudas", "obligaciones"])
    def is_patrimonio(txt):
        return any(k in txt for k in ["patrimonio", "capital"])

    ingresos = Decimal("0"); gastos = Decimal("0"); costo_ventas = Decimal("0"); activo = Decimal("0"); pasivo = Decimal("0"); patrimonio = Decimal("0")
    for c in cuentas:
        txt = txt_map[c.id_cuenta]
        saldo = saldos[c.id_cuenta]
        if is_ingreso(txt):
            ingresos += saldo if nb_map[c.id_cuenta] == "H" else -saldo
        elif is_gasto(txt):
            # separar costos (cuando el texto contiene 'costo')
            val = (saldo if nb_map[c.id_cuenta] == "D" else -saldo)
            gastos += val
            if "costo" in txt:
                costo_ventas += val
        elif is_activo(txt):
            activo += saldo if nb_map[c.id_cuenta] == "D" else -saldo
        elif is_pasivo(txt):
            pasivo += saldo if nb_map[c.id_cuenta] == "H" else -saldo
        elif is_patrimonio(txt):
            patrimonio += saldo if nb_map[c.id_cuenta] == "H" else -saldo
    utilidad = ingresos + gastos  # gastos negativo si mapeo es correcto
    return jsonify(dict(
        er=dict(ingresos=float(ingresos), ventas=float(ingresos), gastos=float(-gastos), costo_ventas=float(-costo_ventas), utilidad=float(utilidad)),
        bg=dict(activo=float(activo), pasivo=float(pasivo), patrimonio=float(patrimonio), pasivo_patrimonio_utilidad=float(pasivo + patrimonio + utilidad)),
    ))

@bp.get("/api/indices")
@login_required
def api_indices():
    empresa_id = _empresa_actual_from_request()
    cuentas = PlanCuenta.query.filter_by(id_empresa=empresa_id).all()
    nb_map = {c.id_cuenta: _normal_side_for(c) for c in cuentas}
    txt_map = {c.id_cuenta: (" ".join(filter(None, [c.rubro, c.subrubro])).lower()) for c in cuentas}
    from decimal import Decimal
    saldos = {c.id_cuenta: Decimal("0") for c in cuentas}
    dets = (
        db.session.query(DetalleAsiento, Asiento)
        .join(Asiento, DetalleAsiento.id_asiento == Asiento.id_asiento)
        .filter(Asiento.id_empresa == empresa_id)
        .all()
    )
    for d, a in dets:
        nb = nb_map.get(d.id_cuenta, "D")
        if d.tipo == "debe":
            saldos[d.id_cuenta] += (d.importe if nb == "D" else -d.importe)
        else:
            saldos[d.id_cuenta] += (d.importe if nb == "H" else -d.importe)
    # Clasificaciones
    def is_activo_corriente(txt):
        keys = ["corriente", "caja", "banco", "bancos", "efectivo", "clientes", "inventario", "existencias"]
        return any(k in txt for k in keys)
    def is_pasivo_corriente(txt):
        keys = ["corriente", "proveedores", "deudas", "obligaciones"]
        return any(k in txt for k in keys)
    def is_activo(txt):
        return any(k in txt for k in ["activo", "caja", "banco", "bancos", "clientes", "inventario", "existencias"])
    def is_pasivo(txt):
        return any(k in txt for k in ["pasivo", "proveedores", "deudas", "obligaciones"])
    def is_patrimonio(txt):
        return any(k in txt for k in ["patrimonio", "capital"]) 
    def is_ingreso(txt):
        return any(k in txt for k in ["ingreso", "ventas", "ingresos"]) 
    def is_gasto(txt):
        return any(k in txt for k in ["gasto", "costos", "costo"]) 

    ac = Decimal("0"); pc = Decimal("0"); a_tot = Decimal("0"); p_tot = Decimal("0"); pat = Decimal("0"); ventas = Decimal("0"); gastos = Decimal("0"); costo_ventas = Decimal("0")
    for c in cuentas:
        txt = txt_map[c.id_cuenta]
        saldo = saldos[c.id_cuenta]
        if is_activo(txt):
            a_tot += saldo if nb_map[c.id_cuenta] == "D" else -saldo
        if is_pasivo(txt):
            p_tot += saldo if nb_map[c.id_cuenta] == "H" else -saldo
        if is_patrimonio(txt):
            pat += saldo if nb_map[c.id_cuenta] == "H" else -saldo
        if is_activo_corriente(txt):
            ac += saldo if nb_map[c.id_cuenta] == "D" else -saldo
        if is_pasivo_corriente(txt):
            pc += saldo if nb_map[c.id_cuenta] == "H" else -saldo
        if is_ingreso(txt):
            ventas += saldo if nb_map[c.id_cuenta] == "H" else -saldo
        if is_gasto(txt):
            val = (saldo if nb_map[c.id_cuenta] == "D" else -saldo)
            gastos += val
            if "costo" in txt:
                costo_ventas += val
    utilidad = ventas + gastos
    def safe_div(n, d):
        try:
            return float(n) / float(d) if float(d) != 0.0 else None
        except Exception:
            return None
    data = dict(
        liquidez=safe_div(ac, pc),
        solvencia=safe_div(a_tot, p_tot),
        endeudamiento=safe_div(p_tot, pat),
        costo_ventas=safe_div(costo_ventas, ventas),
        roi=safe_div(utilidad, pat),
        componentes=dict(activo_corriente=float(ac), pasivo_corriente=float(pc), activo=float(a_tot), pasivo=float(p_tot), patrimonio=float(pat), ventas=float(ventas), utilidad=float(utilidad), costo_ventas=float(costo_ventas))
    )
    return jsonify(data)
