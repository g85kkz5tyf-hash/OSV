from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for

from .constantes import CAMPOS_OJO, TIPOS_RECETA
from .db import get_db
from .utils import parse_importe

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
        compras_anteriores=db.execute(
            "SELECT * FROM compras_anteriores WHERE cliente_id = ?"
            " ORDER BY fecha = '', fecha DESC, id DESC",
            (cliente_id,),
        ).fetchall(),
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
        # La de cerca se guarda antes para que la receta escrita quede como la actual
        extra = guardar_receta_de_cerca(db, cliente_id, datos)
        columnas = list(datos.keys())
        db.execute(
            f"INSERT INTO recetas (cliente_id, {', '.join(columnas)}) "
            f"VALUES (?, {', '.join('?' * len(columnas))})",
            [cliente_id, *datos.values()],
        )
        db.commit()
        flash("Receta guardada." + extra, "ok")
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
        extra = guardar_receta_de_cerca(db, cliente_id, datos)
        db.commit()
        flash("Receta actualizada." + extra, "ok")
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


def a_numero(texto):
    """'+1,50' -> Decimal('1.50'); vacío o «neutro» -> 0; None si no es un número."""
    t = (texto or "").strip().lower().replace(",", ".")
    if t in ("", "n", "neutro", "plano", "pl"):
        return Decimal(0)
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def formato_dioptrias(valor):
    """Decimal('1.5') -> '+1,50'; 0 -> '0,00'; negativo -> '-2,00'."""
    texto = f"{abs(valor):.2f}".replace(".", ",")
    if valor > 0:
        return "+" + texto
    return "-" + texto if valor < 0 else texto


def receta_de_cerca(datos):
    """Copia de la receta para gafas de cerca: esfera + adición en cada ojo y sin adición.

    Devuelve (datos, ojos_sin_calcular).
    """
    cerca = dict(datos, tipo="Gafas cerca")
    sin_calcular = []
    for ojo in ("od", "oi"):
        adicion_texto = datos[f"{ojo}_adicion"]
        if not adicion_texto:
            continue
        esfera, adicion = a_numero(datos[f"{ojo}_esfera"]), a_numero(adicion_texto)
        if esfera is None or adicion is None:
            sin_calcular.append(ojo.upper())
            continue
        cerca[f"{ojo}_esfera"] = formato_dioptrias(esfera + adicion)
        cerca[f"{ojo}_adicion"] = ""
    return cerca, sin_calcular


def guardar_receta_de_cerca(db, cliente_id, datos):
    """Crea la receta de cerca si se pidió al escribir la adición. Devuelve el mensaje a mostrar."""
    if request.form.get("generar_cerca") != "1" or not (datos["od_adicion"] or datos["oi_adicion"]):
        return ""
    cerca, sin_calcular = receta_de_cerca(datos)
    columnas = list(cerca.keys())
    db.execute(
        f"INSERT INTO recetas (cliente_id, {', '.join(columnas)}) VALUES (?, {', '.join('?' * len(columnas))})",
        [cliente_id, *cerca.values()],
    )
    mensaje = " También se creó la receta para gafas de cerca (esfera + adición)."
    if sin_calcular:
        mensaje += f" Revisa la esfera de {' y '.join(sin_calcular)}: no se pudo sumar la adición."
    return mensaje


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


# --- Compras anteriores al programa (solo informativas) ----------------------

def datos_compra_anterior():
    datos = {
        "fecha": request.form.get("fecha", "").strip(),
        "descripcion": request.form.get("descripcion", "").strip(),
        "observaciones": request.form.get("observaciones", "").strip(),
    }
    if not datos["descripcion"]:
        raise ValueError("Escribe qué compró el cliente.")
    datos["importe"] = parse_importe(request.form.get("importe"), None)
    return datos


def obtener_compra_anterior(cliente_id, compra_id):
    compra = get_db().execute(
        "SELECT * FROM compras_anteriores WHERE id = ? AND cliente_id = ?", (compra_id, cliente_id)
    ).fetchone()
    if compra is None:
        abort(404)
    return compra


@bp.route("/<int:cliente_id>/compras-anteriores", methods=["POST"])
def nueva_compra_anterior(cliente_id):
    obtener_cliente(cliente_id)
    try:
        datos = datos_compra_anterior()
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("clientes.ficha", cliente_id=cliente_id) + "#compras-anteriores")
    db = get_db()
    db.execute(
        "INSERT INTO compras_anteriores (cliente_id, fecha, descripcion, importe, observaciones)"
        " VALUES (?, ?, ?, ?, ?)",
        (cliente_id, datos["fecha"], datos["descripcion"], datos["importe"], datos["observaciones"]),
    )
    db.commit()
    flash("Compra anterior añadida a la ficha.", "ok")
    return redirect(url_for("clientes.ficha", cliente_id=cliente_id) + "#compras-anteriores")


@bp.route("/<int:cliente_id>/compras-anteriores/<int:compra_id>/editar", methods=["GET", "POST"])
def editar_compra_anterior(cliente_id, compra_id):
    cliente = obtener_cliente(cliente_id)
    compra = obtener_compra_anterior(cliente_id, compra_id)
    if request.method == "POST":
        try:
            datos = datos_compra_anterior()
        except ValueError as e:
            flash(str(e), "error")
            return redirect(request.url)
        db = get_db()
        db.execute(
            "UPDATE compras_anteriores SET fecha = ?, descripcion = ?, importe = ?, observaciones = ?"
            " WHERE id = ?",
            (datos["fecha"], datos["descripcion"], datos["importe"], datos["observaciones"], compra_id),
        )
        db.commit()
        flash("Compra anterior actualizada.", "ok")
        return redirect(url_for("clientes.ficha", cliente_id=cliente_id) + "#compras-anteriores")
    return render_template("clientes/compra_anterior_form.html", cliente=cliente, compra=compra)


@bp.route("/<int:cliente_id>/compras-anteriores/<int:compra_id>/eliminar", methods=["POST"])
def eliminar_compra_anterior(cliente_id, compra_id):
    obtener_compra_anterior(cliente_id, compra_id)
    db = get_db()
    db.execute("DELETE FROM compras_anteriores WHERE id = ?", (compra_id,))
    db.commit()
    flash("Compra anterior eliminada.", "ok")
    return redirect(url_for("clientes.ficha", cliente_id=cliente_id) + "#compras-anteriores")
