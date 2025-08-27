# utils/scope.py
from flask import g, abort
from models import Empresa, EmpresaEmpleado

def get_user_company_id_or_none():
    if not g.user:
        return None
    # dueño
    e = Empresa.query.filter_by(id_gerente=g.user.id).first()
    if e:
        return e.id_empresa
    # empleado
    rel = EmpresaEmpleado.query.filter_by(id_usuario=g.user.id).first()
    if rel:
        return rel.id_empresa
    return None

def require_company_scope():
    id_emp = get_user_company_id_or_none()
    if id_emp is None and (not g.user or g.user.rol.value != 'docente'):
        abort(403, "No estás afiliado ni eres dueño.")
    return id_emp  # puede ser None si es docente (admin global)
