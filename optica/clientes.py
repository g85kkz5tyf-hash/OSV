from datetime import date

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for

from .constantes import CAMPOS_OJO, TIPOS_RECETA
from .db import get_db

bp = Blueprint("clientes", __name__, url_prefix="/clientes")

CAMPOS_CLIENTE = [
    "nombre", "apellidos", "dni", "fecha_nacimiento", "telefono", "email",
    "direccion", "localidad", "codigo_postal", "notas",
]

CAMPOS_RECETA = (
    ["fecha", "tipo", "optometrista"]
    + [f"{ojo}_{campo}" for ojo in ("od", "oi") for campo, _ in CAMPOS_OJO]
    + ["lc_marca", "lc_curva_base", "lc_diametro", "presion_intraocular",
       "observaciones", "proxima_revision"]
)


def obtener_cliente(cliente_id):
    cliente = get_db().execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    if cliente is None:
        abort(404)
    return cliente


def obtener_receta(cliente_id, receta_id):
    receta = get_db().execute(
        "SELECT * FROM recetas WHERE id = ? AND cliente_id = ?", (receta_id, cliente_id)
    ).fetchone()
    if receta is None:
        abort(404)
    return receta


def buscar_clientes(q, limite=None):
    sql = "SELECT * FROM clientes"
    params = []
    if q:
        patron = f"%{q}%"
        sql += (
            " WHERE nombre || ' ' || apellidos LIKE ? OR apellidos || ' ' || nombre LIKE ?"
            " OR dni LIKE ? OR telefono LIKE ? OR email LIKE ?"
        )
        params = [patron] * 5
    sql += " ORDER BY apellidos COLLATE NOCASE, nombre COLLATE NOCASE"
    if limite:
        sql += f" LIMIT {int(limite)}"
    return get_db().execute(sql, params).fetchall()


@bp.route("/")
def lista():
    q = request.args.get("q", "").strip()
    return render_template("clientes/lista.html", clientes=buscar_clientes(q), q=q)


@bp.route("/nuevo", methods=["GET", "POST"])
def nuevo():
    if request.method == "POST":
        datos = datos_cliente_formulario()
        if not datos["nombre"]:
            flash("El nombre es obligatorio.", "error")
            return render_template("clientes/form.html", cliente=datos)
        db = get_db()
        columnas = list(datos.keys())
        cur = db.execute(
            f"INSERT INTO clientes ({', '.join(columnas)}) VALUES ({', '.join('?' * len(columnas))})",
            [datos[c] for c in columnas],
        )
        db.commit()
        flash("Cliente creado.", "ok")
        return redirect(url_for("clientes.ficha", cliente_id=cur.lastrowid))
    return render_template("clientes/form.html", cliente={})


@bp.route("/<int:cliente_id>/editar", methods=["GET", "POST"])
def editar(cliente_id):
    cliente = obtener_cliente(cliente_id)
    if request.method == "POST":
        datos = datos_cliente_formulario()
        if not datos["nombre"]:
            flash("El nombre es obligatorio.", "error")
            return render_template("clientes/form.html", cliente={**datos, "id": cliente_id})
        db = get_db()
        db.execute(
            f"UPDATE clientes SET {', '.join(f'{c} = ?' for c in datos)} WHERE id = ?",
            [*datos.values(), cliente_id],
        )
        db.commit()
        flash("Datos del cliente guardados.", "ok")
        return redirect(url_for("clientes.ficha", cliente_id=cliente_id))
    return render_template("clientes/form.html", cliente=cliente)


def datos_cliente_formulario():
    datos = {c: request.form.get(c, "").strip() for c in CAMPOS_CLIENTE}
    datos["acepta_comunicaciones"] = 1 if request.form.get("acepta_comunicaciones") else 0
    return datos


@bp.route("/<int:cliente_id>")
def ficha(cliente_id):
    db = get_db()
    cliente = obtener_cliente(cliente_id)
    recetas = db.execute(
        "SELECT * FROM recetas WHERE cliente_id = ? ORDER BY fecha DESC, id DESC", (cliente_id,)
    ).fetchall()
    ventas = db.execute(
        """
        SELECT v.*, COALESCE((SELECT SUM(importe) FROM pagos WHERE venta_id = v.id), 0) AS pagado
        FROM ventas v WHERE v.cliente_id = ? ORDER BY v.fecha DESC, v.id DESC
        """,
        (cliente_id,),
    ).fetchall()
    lineas = {}
    for linea in db.execute(
        """
        SELECT l.* FROM lineas_venta l JOIN ventas v ON v.id = l.venta_id
        WHERE v.cliente_id = ? ORDER BY l.id
        """,
        (cliente_id,),
    ):
        lineas.setdefault(linea["venta_id"], []).append(linea)
    validas = [v for v in ventas if v["estado"] != "Anulada"]
    resumen = {
        "total_comprado": sum(v["total"] for v in validas),
        "pendiente": sum(v["total"] - v["pagado"] for v in validas),
        "num_compras": len(validas),
    }
    return render_template(
        "clientes/ficha.html",
        cliente=cliente, recetas=recetas, ventas=ventas, lineas=lineas,
        resumen=resumen, campos_ojo=CAMPOS_OJO,
    )


@bp.route("/<int:cliente_id>/eliminar", methods=["POST"])
def eliminar(cliente_id):
    obtener_cliente(cliente_id)
    db = get_db()
    tiene_ventas = db.execute("SELECT 1 FROM ventas WHERE cliente_id = ? LIMIT 1", (cliente_id,)).fetchone()
    if tiene_ventas:
        flash("No se puede eliminar un cliente con ventas registradas.", "error")
        return redirect(url_for("clientes.ficha", cliente_id=cliente_id))
    db.execute("DELETE FROM clientes WHERE id = ?", (cliente_id,))
    db.commit()
    flash("Cliente eliminado.", "ok")
    return redirect(url_for("clientes.lista"))


# --- Recetas -----------------------------------------------------------------

@bp.route("/<int:cliente_id>/recetas/nueva", methods=["GET", "POST"])
def nueva_receta(cliente_id):
    cliente = obtener_cliente(cliente_id)
    if request.method == "POST":
        datos = datos_receta_formulario()
        db = get_db()
        columnas = list(datos.keys())
        db.execute(
            f"INSERT INTO recetas (cliente_id, {', '.join(columnas)}) "
            f"VALUES (?, {', '.join('?' * len(columnas))})",
            [cliente_id, *datos.values()],
        )
        db.commit()
        flash("Receta guardada.", "ok")
        return redirect(url_for("clientes.ficha", cliente_id=cliente_id) + "#recetas")
    receta = {"fecha": date.today().isoformat(), "tipo": TIPOS_RECETA[0]}
    # Proponer la última optometrista usada para agilizar
    ultima = get_db().execute("SELECT optometrista FROM recetas ORDER BY id DESC LIMIT 1").fetchone()
    if ultima:
        receta["optometrista"] = ultima["optometrista"]
    return render_template(
        "clientes/receta_form.html", cliente=cliente, receta=receta,
        tipos=TIPOS_RECETA, campos_ojo=CAMPOS_OJO,
    )


@bp.route("/<int:cliente_id>/recetas/<int:receta_id>/editar", methods=["GET", "POST"])
def editar_receta(cliente_id, receta_id):
    cliente = obtener_cliente(cliente_id)
    receta = obtener_receta(cliente_id, receta_id)
    if request.method == "POST":
        datos = datos_receta_formulario()
        db = get_db()
        db.execute(
            f"UPDATE recetas SET {', '.join(f'{c} = ?' for c in datos)} WHERE id = ?",
            [*datos.values(), receta_id],
        )
        db.commit()
        flash("Receta actualizada.", "ok")
        return redirect(url_for("clientes.ficha", cliente_id=cliente_id) + "#recetas")
    return render_template(
        "clientes/receta_form.html", cliente=cliente, receta=receta,
        tipos=TIPOS_RECETA, campos_ojo=CAMPOS_OJO,
    )


@bp.route("/<int:cliente_id>/recetas/<int:receta_id>")
def imprimir_receta(cliente_id, receta_id):
    cliente = obtener_cliente(cliente_id)
    receta = obtener_receta(cliente_id, receta_id)
    return render_template(
        "clientes/receta_imprimir.html", cliente=cliente, receta=receta, campos_ojo=CAMPOS_OJO
    )


@bp.route("/<int:cliente_id>/recetas/<int:receta_id>/eliminar", methods=["POST"])
def eliminar_receta(cliente_id, receta_id):
    obtener_receta(cliente_id, receta_id)
    db = get_db()
    if db.execute("SELECT 1 FROM ventas WHERE receta_id = ? LIMIT 1", (receta_id,)).fetchone():
        flash("La receta está asociada a una venta y no se puede eliminar.", "error")
    else:
        db.execute("DELETE FROM recetas WHERE id = ?", (receta_id,))
        db.commit()
        flash("Receta eliminada.", "ok")
    return redirect(url_for("clientes.ficha", cliente_id=cliente_id) + "#recetas")


def datos_receta_formulario():
    datos = {c: request.form.get(c, "").strip() for c in CAMPOS_RECETA}
    if not datos["fecha"]:
        datos["fecha"] = date.today().isoformat()
    return datos


# --- API para el formulario de ventas ----------------------------------------

@bp.route("/api/buscar")
def api_buscar():
    q = request.args.get("q", "").strip()
    return jsonify([
        {"id": c["id"], "nombre": f"{c['nombre']} {c['apellidos']}".strip(),
         "dni": c["dni"], "telefono": c["telefono"]}
        for c in buscar_clientes(q, limite=15)
    ])


@bp.route("/api/<int:cliente_id>/recetas")
def api_recetas(cliente_id):
    recetas = get_db().execute(
        "SELECT id, fecha, tipo FROM recetas WHERE cliente_id = ? ORDER BY fecha DESC, id DESC",
        (cliente_id,),
    ).fetchall()
    return jsonify([dict(r) for r in recetas])
