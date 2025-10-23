# App Contabilidad – Estructura modular

Este módulo está organizado en blueprints y plantillas modulares para separar responsabilidades entre autenticación, empresas, contabilidad, administración y reportes.

## Estructura

```
app-contabilidad/
  app-contabilidad/
    app.py                      # App factory y registro de blueprints
    config.py                   # Configuración (Flask, SQLAlchemy, OAuth)
    models.py                   # Modelos (Usuarios, Empresas, Contabilidad)

    accounting.py               # Blueprint Contabilidad (rutas y lógica web)
    companies.py                # Blueprint Empresas
    auth.py                     # Blueprint Auth (Google OAuth y sesiones)
    admin/                      # Blueprint Admin
    reports/                    # Blueprint Reports

    templates/
      base.html                 # Layout base (estilos y slots)
      home.html                 # Home con accesos a módulos
      accounting/
        mini.html               # Nueva UI integrada (reemplazo total)
        journal_list.html       # (Obsoleto) redirigido a mini
        journal_new.html        # (Obsoleto)
        mayor.html              # (Obsoleto)

    static/
      accounting/
        mini.css                # (Sugerido) estilos de la nueva UI
        mini.js                 # (Sugerido) lógica de UI
        api.js                  # (Sugerido) cliente REST hacia backend

    test-libro/
      index.html                # Origen de la nueva UI (ya integrado como mini.html)
```

## Reemplazo de funciones obsoletas

- La ruta `GET /accounting/journal` (endpoint `accounting.journal_list`) ahora redirige automáticamente a `GET /accounting/mini`.
- La nueva pantalla `mini.html` es la interfaz oficial del módulo contable.
- En `home.html` se agregó el botón "Mini Contable" y se corrigió el enlace del panel contable.

## Comportamiento por rol y empresas

- Dueño/empleado: la empresa se resuelve automáticamente y se pasa a la UI.
- Docente: en la cabecera de `mini.html` se muestra un selector de empresa. Al elegir una, la vista se recarga con `?empresa=ID`.

## Plan de modularización frontend (sugerido)

Para completar la modularización del frontend:
- Mover estilos/JS embebidos de `mini.html` a `static/accounting/mini.css` y `static/accounting/mini.js`.
- Extraer la capa de acceso a datos a `static/accounting/api.js`.
- Hacer que `mini.html` extienda `base.html` y cargue los assets desde `static/`.

## Plan de APIs (sin cambios de esquema)

Para reemplazar `localStorage` por backend, sin modificar columnas, se propone:
- Exponer endpoints REST en `accounting.py` bajo `/accounting/api/*` que operen sobre los modelos existentes:
  - `GET /accounting/api/cuentas?empresa=ID` – listar `PlanCuenta` por empresa.
  - `POST /accounting/api/asientos` – crear `Asiento` + `DetalleAsiento` con validaciones (Debe=Haber>0).
  - `GET /accounting/api/asientos?empresa=ID` – listar asientos con sus detalles.
  - `GET /accounting/api/mayor?empresa=ID&cuenta=ID` – calcular movimientos y saldo.
  - `GET /accounting/api/balance?empresa=ID` – balance de comprobación.
  - `GET /accounting/api/estados?empresa=ID` – resultados y balance general.

Nota: como el modelo actual no incluye `tipo` ni `codigo` en `PlanCuenta`, los cálculos (mayor, balance, estados) deberán derivar la naturaleza de saldo a partir de `rubro/subrubro` mediante una tabla de mapeo en backend.

## Puesta en marcha

- Variables `.env` (DB, OAuth) según `config.py`.
- Ejecutar:

```bash
python app.py
```

- Acceso:
  - Home: `http://localhost:5000/`
  - Mini Contable: `http://localhost:5000/accounting/mini`

## Notas

- `journal_list.html` y páginas relacionadas quedan como referencia, pero la navegación estándar ya usa `mini.html`.
- Se recomienda progresivamente migrar la lógica embebida en `mini.html` a archivos en `static/` y a APIs REST para abandonar `localStorage`.
