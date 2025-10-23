from functools import wraps
from flask import g, redirect, url_for, request, abort


def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if not getattr(g, "user", None):
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return wrap


def roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrap(*args, **kwargs):
            user = getattr(g, "user", None)
            if not user:
                return redirect(url_for("auth.login", next=request.path))
            if user.rol.name not in roles and user.rol.value not in roles:
                abort(403)
            return f(*args, **kwargs)
        return wrap
    return decorator


def empresa_required(get_empresa_id_func):
    """
    Asegura que exista un contexto de empresa válido antes de entrar a la vista.
    get_empresa_id_func: callable que devuelve id_empresa o None, según el usuario/qs.
    """
    def decorator(f):
        @wraps(f)
        def wrap(*args, **kwargs):
            empresa_id = get_empresa_id_func()
            if not empresa_id:
                # redirige a selección de empresa (ruta a definir en auth/companies)
                return redirect(url_for("companies.list_companies"))
            return f(*args, **kwargs)
        return wrap
    return decorator
