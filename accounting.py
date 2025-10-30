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
        emp = request.args.get("empresa", type=int) or request.json.get("empresa") if request.is_json else None
        if not emp:
            abort(400, description="Se requiere parametro empresa para rol docente")
        return emp
    emp = _empresa_del_usuario()
    if not emp:
        abort(400, description="Usuario sin empresa asociada")
    return emp

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
    # Datos de entrada: codigo, nombre, tipo (Activo/Pasivo/Patrimonio/Ingreso/Gasto)
    codigo = (payload.get("codigo") or "").strip().upper()
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
        if sr.startswith("ingresos"):
            rubro = "Ingresos"
        else:
            rubro = "Gastos"
    elif tipo_norm in ("ingreso","ingresos"):
        rubro = "Ingresos"
    elif tipo_norm in ("gasto","gastos"):
        rubro = "Gastos"
    # Crear registro mínimo
    pc = PlanCuenta(
        id_empresa=empresa_id,
        cuenta=nombre,
        cod_rubro=codigo or None,
        rubro=rubro,
        cod_subrubro=(payload.get("cod_subrubro") or None),
        subrubro=(payload.get("subrubro") or None),
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
            datos=f"{{\"codigo\":\"{codigo}\",\"nombre\":\"{nombre}\",\"tipo\":\"{tipo}\"}}",
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


@bp.route('/api/asientos', methods=['POST'])
@login_required
def api_asientos_create():
    try:
        data = request.get_json()
        if not data or 'detalles' not in data or not data['detalles']:
            return jsonify({'error': 'Datos de asiento inválidos'}), 400

        id_empresa = _empresa_actual_from_request()
        if not id_empresa:
            return jsonify({'error': 'Empresa no especificada'}), 400

        # Obtener el próximo número de asiento
        ultimo_asiento = Asiento.query.filter_by(id_empresa=id_empresa)\
                                    .order_by(Asiento.num_asiento.desc()).first()
        num_asiento = 1 if not ultimo_asiento else ultimo_asiento.num_asiento + 1

        # Crear el asiento
        asiento = Asiento(
            id_empresa=id_empresa,
            num_asiento=num_asiento,
            fecha=data.get('fecha') or date.today(),
            doc_respaldatorio=data.get('doc_respaldatorio'),
            id_usuario=g.user.id,
            leyenda=data.get('leyenda')
        )

        # Validar y crear detalles
        total_debe = Decimal('0')
        total_haber = Decimal('0')
        
        for det in data['detalles']:
            if 'id_cuenta' not in det or 'tipo' not in det or 'importe' not in det:
                db.session.rollback()
                return jsonify({'error': 'Faltan campos requeridos en los detalles'}), 400
            
            if det['tipo'] not in ('debe', 'haber'):
                db.session.rollback()
                return jsonify({'error': 'Tipo de asiento debe ser "debe" o "haber"'}), 400
            
            try:
                importe = Decimal(str(det['importe']))
                if importe <= 0:
                    raise ValueError("El importe debe ser mayor a cero")
            except (ValueError, TypeError):
                db.session.rollback()
                return jsonify({'error': 'Importe inválido'}), 400
            
            if det['tipo'] == 'debe':
                total_debe += importe
            else:
                total_haber += importe
            
            detalle = DetalleAsiento(
                id_cuenta=det['id_cuenta'],
                tipo=det['tipo'],
                importe=importe
            )
            asiento.detalles.append(detalle)
        
        # Validar que los totales coincidan
        if total_debe != total_haber:
            db.session.rollback()
            return jsonify({
                'error': 'Los totales de debe y haber no coinciden',
                'total_debe': str(total_debe),
                'total_haber': str(total_haber)
            }), 400

        # Guardar en la base de datos
        db.session.add(asiento)
        
        # Registrar en el log
        log = ChangeLog(
            entidad='asiento',
            id_entidad=asiento.id_asiento,
            accion='create',
            id_usuario=g.user.id,
            datos=f"Asiento #{num_asiento} - {asiento.leyenda or 'Sin descripción'}"
        )
        db.session.add(log)
        
        db.session.commit()
        
        return jsonify({
            'message': 'Asiento creado exitosamente',
            'id_asiento': asiento.id_asiento,
            'num_asiento': asiento.num_asiento
        }), 201
        
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({'error': 'Error al crear el asiento: ' + str(e)}), 500

@bp.route('/api/asientos/<int:id_asiento>', methods=['DELETE'])
@login_required
def api_asientos_delete(id_asiento):
    try:
        # Obtener la empresa del usuario actual
        id_empresa = _empresa_actual_from_request()
        if not id_empresa:
            return jsonify({'error': 'Empresa no especificada o no autorizada'}), 403

        # Buscar el asiento con sus detalles
        asiento = Asiento.query.filter_by(
            id_asiento=id_asiento,
            id_empresa=id_empresa
        ).first()

        if not asiento:
            return jsonify({'error': 'Asiento no encontrado o no autorizado'}), 404

        # Guardar datos para el log antes de eliminar
        num_asiento = asiento.num_asiento
        leyenda = asiento.leyenda or 'Sin descripción'

        # Eliminar el asiento (los detalles se eliminan en cascada)
        db.session.delete(asiento)

        # Registrar en el log
        log = ChangeLog(
            entidad='asiento',
            id_entidad=id_asiento,
            accion='delete',
            id_usuario=g.user.id,
            datos=f"Eliminado asiento #{num_asiento} - {leyenda}"
        )
        db.session.add(log)
        
        db.session.commit()

        return jsonify({
            'message': 'Asiento eliminado exitosamente',
            'id_asiento': id_asiento,
            'num_asiento': num_asiento
        })

    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({'error': 'Error al eliminar el asiento: ' + str(e)}), 500

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

@bp.get("/api/estados")
@login_required
def api_estados():
    empresa_id = _empresa_actual_from_request()
    cuentas = PlanCuenta.query.filter_by(id_empresa=empresa_id).all()
    nb_map = {c.id_cuenta: _normal_side_for(c) for c in cuentas}
    txt_map = {c.id_cuenta: (" ".join(filter(None, [c.rubro, c.subrubro])).lower()) for c in cuentas}
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
