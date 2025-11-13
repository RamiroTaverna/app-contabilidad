# services/plan.py
from models import db
from models import Empresa  # si lo necesitaras para checks
from sqlalchemy import text

def clonar_plan_para_empresa(id_empresa: int):
    """
    Copia todas las filas de plan_cuentas_plantilla a plan_cuentas con id_empresa dado.
    Usa SQL directo para ser eficiente.
    """
    sql = text("""
        INSERT INTO plan_cuentas (id_empresa, cod_rubro, rubro, cod_subrubro, subrubro, cuenta)
        SELECT :id_empresa, cod_rubro, rubro, cod_subrubro, subrubro, cuenta
        FROM plan_cuentas_plantilla
    """)
    db.session.execute(sql, {"id_empresa": id_empresa})
