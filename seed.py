# seed.py
from app import app, db
from models import Usuario, Empresa, EmpresaEmpleado, Rol
with app.app_context():
    # usuario empleado de prueba (si no existe)
    u = Usuario.query.filter_by(correo="empleado@test.local").first()
    if not u:
        u = Usuario(nombre="Empleado Test", correo="empleado@test.local", rol=Rol.empleado)
        db.session.add(u); db.session.commit()

    # crear empresa con dueño = ese empleado (lo subimos a dueño)
    u.rol = Rol.dueno
    e = Empresa(nombre="Team Demo", id_gerente=u.id)
    db.session.add(e); db.session.commit()
    print("OK: creada empresa Team Demo con dueño Empleado Test")
