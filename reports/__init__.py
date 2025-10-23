from flask import Blueprint, render_template, request, g, redirect, url_for, abort, send_file, make_response
from io import BytesIO
from accounting import _empresa_del_usuario
from models import db, Asiento, DetalleAsiento, PlanCuenta

bp = Blueprint("reports", __name__, url_prefix="/reports")

def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrap(*args, **kwargs):
        if not getattr(g, "user", None):
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return wrap

def owners_employees_only(f):
    from functools import wraps
    @wraps(f)
    def wrap(*args, **kwargs):
        if not getattr(g, "user", None):
            return redirect(url_for("auth.login", next=request.path))
        # Solo dueños o empleados
        role = getattr(getattr(g, "user", None), "rol", None)
        if not role or role.value not in ("dueno", "empleado"):
            abort(403)
        return f(*args, **kwargs)
    return wrap

@bp.route("/")
@login_required
@owners_employees_only
def index():
    return render_template("reports/index.html")

# Libro Diario
@bp.route("/diario")
@login_required
@owners_employees_only
def diario():
    return render_template("reports/diario.html")

@bp.route("/diario/export")
@login_required
@owners_employees_only
def diario_export_pdf():
    # Determinar empresa del usuario (docentes no acceden a reportes)
    emp_id = _empresa_del_usuario()
    if not emp_id:
        abort(400, description="Usuario sin empresa asociada")
    # Traer asientos con detalles
    rows = (
        db.session.query(Asiento, DetalleAsiento, PlanCuenta)
        .outerjoin(DetalleAsiento, DetalleAsiento.id_asiento == Asiento.id_asiento)
        .outerjoin(PlanCuenta, PlanCuenta.id_cuenta == DetalleAsiento.id_cuenta)
        .filter(Asiento.id_empresa == emp_id)
        .order_by(Asiento.fecha.asc(), Asiento.num_asiento.asc(), DetalleAsiento.id_detalle.asc())
        .all()
    )
    # Estructurar por asiento
    diario = []
    cur = None
    last_id = None
    for a, d, pc in rows:
        if a.id_asiento != last_id:
            cur = dict(id=a.id_asiento, fecha=a.fecha.isoformat(), num=a.num_asiento, leyenda=a.leyenda or "", detalles=[])
            diario.append(cur)
            last_id = a.id_asiento
        if d is not None:
            cur["detalles"].append(dict(cuenta=(pc.cuenta if pc else ''), tipo=d.tipo, importe=float(d.importe)))
    # Renderizar HTML
    html = render_template("reports/diario_pdf.html", diario=diario)
    # Intentar generar PDF con xhtml2pdf
    try:
        from xhtml2pdf import pisa
        pdf_io = BytesIO()
        pisa.CreatePDF(html, dest=pdf_io)
        pdf_io.seek(0)
        return send_file(pdf_io, mimetype="application/pdf", as_attachment=True, download_name="libro_diario.pdf")
    except Exception:
        # Fallback a HTML descargable
        resp = make_response(html)
        resp.headers['Content-Type'] = 'text/html; charset=utf-8'
        resp.headers['Content-Disposition'] = 'attachment; filename=libro_diario.html'
        return resp

# Libro Mayor
@bp.route("/mayor")
@login_required
@owners_employees_only
def mayor():
    return render_template("reports/mayor.html")

# Graficos
@bp.route("/graficos")
@login_required
@owners_employees_only
def graficos():
    return render_template("reports/graficos.html")

# Estado de Situacion Patrimonial
@bp.route("/estado")
@login_required
@owners_employees_only
def estado():
    return render_template("reports/estado_patrimonial.html")

# Balance de Comprobacion
@bp.route("/balance")
@login_required
@owners_employees_only
def balance():
    return render_template("reports/balance.html")

# Indices
@bp.route("/indices")
@login_required
@owners_employees_only
def indices():
    return render_template("reports/indices.html")
