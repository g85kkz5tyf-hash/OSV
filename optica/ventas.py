from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .constantes import CAMPOS_OJO, ESTADOS_ABIERTOS, ESTADOS_VENTA, METODOS_PAGO, TIPOS_IVA
from .db import get_config, get_db
from .productos import nombre_producto, registrar_movimiento
from .utils import desglose_iva, importe_linea, parse_entero, parse_importe

bp = Blueprint("ventas", __name__, url_prefix="/ventas")

SQL_VENTAS = """
    SELECT v.*,
           COALESCE((SELECT SUM(importe) FROM pagos WHERE venta_id = v.id), 0) AS pagado,
           TRIM(COALESCE(c.nombre, '') || ' ' || COALESCE(c.apellidos, '')) AS cliente_nombre
    FROM ventas v LEFT JOIN clientes c ON c.id = v.cliente_id
"""


class ErrorVenta(Exception):
    pass


def obtener_venta(venta_id):
    venta = get_db().execute(SQL_VENTAS + " WHERE v.id = ?", (venta_id,)).fetchone()
    if venta is None:
        abort(404)
    return venta


def siguiente_numero(db):
    anio = date.today().year
    ultimo = db.execute(
        "SELECT numero FROM ventas WHERE numero LIKE ? ORDER BY numero DESC LIMIT 1", (f"{anio}-%",)
    ).fetchone()
    n = int(ultimo["numero"].split("-")[1]) + 1 if ultimo else 1
    return f"{anio}-{n:05d}"


@bp.route("/")
def lista():
    q = request.args.get("q", "").strip()
    estado = request.args.get("estado", "")
    desde = request.args.get("desde", "")
    hasta = request.args.get("hasta", "")
    sql = SQL_VENTAS + " WHERE 1=1"
    params = []
    if q:
        sql += " AND (v.numero LIKE ? OR c.nombre || ' ' || c.apellidos LIKE ? OR c.dni LIKE ?)"
        params += [f"%{q}%"] * 3
    if estado == "abiertos":
        sql += f" AND v.estado IN ({', '.join('?' * len(ESTADOS_ABIERTOS))})"
        params += ESTADOS_ABIERTOS
    elif estado == "pendiente_cobro":
        sql += " AND v.estado != 'Anulada' AND v.total > COALESCE((SELECT SUM(importe) FROM pagos WHERE venta_id = v.id), 0)"
    elif estado:
        sql += " AND v.estado = ?"
        params.append(estado)
    if desde:
        sql += " AND date(v.fecha) >= ?"
        params.append(desde)
    if hasta:
        sql += " AND date(v.fecha) <= ?"
        params.append(hasta)
    sql += " ORDER BY v.fecha DESC, v.id DESC LIMIT 500"
    ventas = get_db().execute(sql, params).fetchall()
    validas = [v for v in ventas if v["estado"] != "Anulada"]
    return render_template(
        "ventas/lista.html", ventas=ventas, q=q, estado=estado, desde=desde, hasta=hasta,
        estados=ESTADOS_VENTA, total=sum(v["total"] for v in validas),
        pendiente=sum(v["total"] - v["pagado"] for v in validas),
    )


def leer_lineas_formulario(db):
    """Lee las líneas enviadas por el formulario y las valida contra el stock."""
    f = request.form
    producto_ids = f.getlist("producto_id")
    descripciones = f.getlist("descripcion")
    cantidades = f.getlist("cantidad")
    precios = f.getlist("precio")
    descuentos = f.getlist("descuento")
    ivas = f.getlist("iva")
    lineas = []
    necesidades = {}
    for i, descripcion in enumerate(descripciones):
        descripcion = descripcion.strip()
        producto_id = producto_ids[i].strip() if i < len(producto_ids) else ""
        if not descripcion and not producto_id:
            continue
        try:
            cantidad = parse_entero(cantidades[i], 1)
            precio = parse_importe(precios[i])
            descuento = parse_entero(descuentos[i], 0)
            iva = parse_entero(ivas[i], TIPOS_IVA[0])
        except (ValueError, IndexError) as e:
            raise ErrorVenta(f"Línea {i + 1}: {e}")
        if cantidad <= 0:
            raise ErrorVenta(f"Línea {i + 1}: la cantidad debe ser mayor que cero.")
        if not 0 <= descuento <= 100:
            raise ErrorVenta(f"Línea {i + 1}: el descuento debe estar entre 0 y 100.")
        if precio < 0:
            raise ErrorVenta(f"Línea {i + 1}: el precio no puede ser negativo.")
        producto = None
        if producto_id:
            producto = db.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
            if producto is None:
                raise ErrorVenta(f"Línea {i + 1}: el producto no existe.")
            iva = producto["iva"]
            if not descripcion:
                descripcion = nombre_producto(producto)
            if producto["controla_stock"]:
                necesidades[producto["id"]] = necesidades.get(producto["id"], 0) + cantidad
                if necesidades[producto["id"]] > producto["stock"]:
                    raise ErrorVenta(
                        f"No hay stock suficiente de «{descripcion}» "
                        f"(disponible: {producto['stock']}, solicitado: {necesidades[producto['id']]})."
                    )
        if not producto and iva not in TIPOS_IVA:
            raise ErrorVenta(f"Línea {i + 1}: tipo de IVA no válido.")
        lineas.append({
            "producto": producto,
            "descripcion": descripcion,
            "cantidad": cantidad,
            "precio_unitario": precio,
            "descuento_pct": descuento,
            "iva": iva,
            "importe": importe_linea(cantidad, precio, descuento),
        })
    if not lineas:
        raise ErrorVenta("Añade al menos una línea a la venta.")
    return lineas


def crear_venta(db, cliente_id, receta_id, lineas, estado, entrega_prevista, notas, pago, metodo):
    total = sum(l["importe"] for l in lineas)
    if pago > total:
        raise ErrorVenta("El importe cobrado no puede superar el total de la venta.")
    numero = siguiente_numero(db)
    cur = db.execute(
        "INSERT INTO ventas (numero, cliente_id, receta_id, total, estado, fecha_entrega_prevista, notas)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (numero, cliente_id, receta_id, total, estado, entrega_prevista, notas),
    )
    venta_id = cur.lastrowid
    for l in lineas:
        producto = l["producto"]
        db.execute(
            "INSERT INTO lineas_venta (venta_id, producto_id, descripcion, cantidad, precio_unitario,"
            " descuento_pct, iva, importe) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (venta_id, producto["id"] if producto else None, l["descripcion"], l["cantidad"],
             l["precio_unitario"], l["descuento_pct"], l["iva"], l["importe"]),
        )
        if producto and producto["controla_stock"]:
            registrar_movimiento(db, producto["id"], -l["cantidad"], "venta", f"Venta {numero}", venta_id)
    if pago:
        db.execute(
            "INSERT INTO pagos (venta_id, importe, metodo) VALUES (?, ?, ?)", (venta_id, pago, metodo)
        )
    return venta_id


@bp.route("/nueva", methods=["GET", "POST"])
def nueva():
    db = get_db()
    if request.method == "POST":
        f = request.form
        cliente_id = parse_entero(f.get("cliente_id"), None) if f.get("cliente_id", "").isdigit() else None
        receta_id = parse_entero(f.get("receta_id"), None) if f.get("receta_id", "").isdigit() else None
        estado = f.get("estado", "Entregado")
        metodo = f.get("metodo", METODOS_PAGO[0])
        try:
            if estado not in ESTADOS_VENTA or estado == "Anulada":
                raise ErrorVenta("Estado no válido.")
            if metodo not in METODOS_PAGO:
                raise ErrorVenta("Método de pago no válido.")
            if cliente_id and not db.execute("SELECT 1 FROM clientes WHERE id = ?", (cliente_id,)).fetchone():
                raise ErrorVenta("El cliente no existe.")
            if receta_id and not db.execute(
                "SELECT 1 FROM recetas WHERE id = ? AND cliente_id IS ?", (receta_id, cliente_id)
            ).fetchone():
                raise ErrorVenta("La receta no pertenece al cliente seleccionado.")
            try:
                pago = parse_importe(f.get("pago"))
            except ValueError as e:
                raise ErrorVenta(str(e))
            if pago < 0:
                raise ErrorVenta("El importe cobrado no puede ser negativo.")
            lineas = leer_lineas_formulario(db)
            venta_id = crear_venta(
                db, cliente_id, receta_id, lineas, estado,
                f.get("fecha_entrega_prevista", "").strip(), f.get("notas", "").strip(), pago, metodo,
            )
        except ErrorVenta as e:
            db.rollback()
            flash(str(e), "error")
            return render_template("ventas/nueva.html", **contexto_nueva(request.form))
        db.commit()
        flash("Venta registrada.", "ok")
        return redirect(url_for("ventas.detalle", venta_id=venta_id))
    return render_template("ventas/nueva.html", **contexto_nueva(None))


def contexto_nueva(form):
    db = get_db()
    cliente = None
    cliente_id = (form.get("cliente_id") if form else request.args.get("cliente_id", "")) or ""
    if cliente_id.isdigit():
        cliente = db.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    recetas = []
    if cliente:
        recetas = db.execute(
            "SELECT id, fecha, tipo FROM recetas WHERE cliente_id = ? ORDER BY fecha DESC, id DESC",
            (cliente["id"],),
        ).fetchall()
    lineas = []
    if form:
        for i, descripcion in enumerate(form.getlist("descripcion")):
            lineas.append({
                "producto_id": form.getlist("producto_id")[i],
                "descripcion": descripcion,
                "cantidad": form.getlist("cantidad")[i],
                "precio": form.getlist("precio")[i],
                "descuento": form.getlist("descuento")[i],
                "iva": form.getlist("iva")[i],
            })
    return {
        "cliente": cliente, "recetas": recetas, "form": form or {}, "lineas": lineas,
        "estados": [e for e in ESTADOS_VENTA if e != "Anulada"], "metodos": METODOS_PAGO,
        "tipos_iva": TIPOS_IVA,
    }


@bp.route("/<int:venta_id>")
def detalle(venta_id):
    db = get_db()
    venta = obtener_venta(venta_id)
    lineas = db.execute("SELECT * FROM lineas_venta WHERE venta_id = ? ORDER BY id", (venta_id,)).fetchall()
    pagos = db.execute("SELECT * FROM pagos WHERE venta_id = ? ORDER BY id", (venta_id,)).fetchall()
    cliente = receta = None
    if venta["cliente_id"]:
        cliente = db.execute("SELECT * FROM clientes WHERE id = ?", (venta["cliente_id"],)).fetchone()
    if venta["receta_id"]:
        receta = db.execute("SELECT * FROM recetas WHERE id = ?", (venta["receta_id"],)).fetchone()
    return render_template(
        "ventas/detalle.html", venta=venta, lineas=lineas, pagos=pagos, cliente=cliente,
        receta=receta, estados=[e for e in ESTADOS_VENTA if e != "Anulada"], metodos=METODOS_PAGO,
        desglose=desglose_iva(lineas), campos_ojo=CAMPOS_OJO,
    )


@bp.route("/<int:venta_id>/ticket")
def ticket(venta_id):
    db = get_db()
    venta = obtener_venta(venta_id)
    lineas = db.execute("SELECT * FROM lineas_venta WHERE venta_id = ? ORDER BY id", (venta_id,)).fetchall()
    pagos = db.execute("SELECT * FROM pagos WHERE venta_id = ? ORDER BY id", (venta_id,)).fetchall()
    cliente = None
    if venta["cliente_id"]:
        cliente = db.execute("SELECT * FROM clientes WHERE id = ?", (venta["cliente_id"],)).fetchone()
    return render_template(
        "ventas/ticket.html", venta=venta, lineas=lineas, pagos=pagos, cliente=cliente,
        desglose=desglose_iva(lineas), config=get_config(db),
    )


@bp.route("/<int:venta_id>/pago", methods=["POST"])
def pago(venta_id):
    venta = obtener_venta(venta_id)
    if venta["estado"] == "Anulada":
        abort(400)
    metodo = request.form.get("metodo")
    try:
        importe = parse_importe(request.form.get("importe"))
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("ventas.detalle", venta_id=venta_id))
    pendiente = venta["total"] - venta["pagado"]
    if importe <= 0 or importe > pendiente:
        flash("El importe debe ser mayor que cero y no superar lo pendiente.", "error")
    elif metodo not in METODOS_PAGO:
        flash("Método de pago no válido.", "error")
    else:
        db = get_db()
        db.execute("INSERT INTO pagos (venta_id, importe, metodo) VALUES (?, ?, ?)", (venta_id, importe, metodo))
        db.commit()
        flash("Cobro registrado.", "ok")
    return redirect(url_for("ventas.detalle", venta_id=venta_id))


@bp.route("/<int:venta_id>/estado", methods=["POST"])
def estado(venta_id):
    venta = obtener_venta(venta_id)
    nuevo = request.form.get("estado")
    if venta["estado"] == "Anulada" or nuevo not in ESTADOS_VENTA or nuevo == "Anulada":
        abort(400)
    db = get_db()
    db.execute(
        "UPDATE ventas SET estado = ?, fecha_entrega_prevista = ?, notas = ? WHERE id = ?",
        (nuevo, request.form.get("fecha_entrega_prevista", "").strip(),
         request.form.get("notas", "").strip(), venta_id),
    )
    db.commit()
    flash("Venta actualizada.", "ok")
    return redirect(url_for("ventas.detalle", venta_id=venta_id))


@bp.route("/<int:venta_id>/cambiar-estado", methods=["POST"])
def cambiar_estado(venta_id):
    """Cambio rápido de estado desde la lista de encargos (no toca notas ni fechas)."""
    venta = obtener_venta(venta_id)
    nuevo = request.form.get("estado")
    if venta["estado"] == "Anulada" or nuevo not in ESTADOS_VENTA or nuevo == "Anulada":
        abort(400)
    db = get_db()
    db.execute("UPDATE ventas SET estado = ? WHERE id = ?", (nuevo, venta_id))
    db.commit()
    flash(f"Venta {venta['numero']}: estado cambiado a «{nuevo}».", "ok")
    volver = request.form.get("volver", "")
    if not volver.startswith("/") or volver.startswith("//"):
        volver = url_for("main.inicio")
    return redirect(volver)


@bp.route("/<int:venta_id>/anular", methods=["POST"])
def anular(venta_id):
    venta = obtener_venta(venta_id)
    if venta["estado"] == "Anulada":
        abort(400)
    db = get_db()
    # Devolver al stock los productos vendidos
    for l in db.execute(
        "SELECT l.producto_id, l.cantidad FROM lineas_venta l JOIN productos p ON p.id = l.producto_id"
        " WHERE l.venta_id = ? AND p.controla_stock = 1",
        (venta_id,),
    ).fetchall():
        registrar_movimiento(db, l["producto_id"], l["cantidad"], "anulacion",
                             f"Anulación venta {venta['numero']}", venta_id)
    # Registrar la devolución del dinero cobrado, por cada método de pago
    for p in db.execute(
        "SELECT metodo, SUM(importe) AS total FROM pagos WHERE venta_id = ? GROUP BY metodo", (venta_id,)
    ).fetchall():
        if p["total"]:
            db.execute(
                "INSERT INTO pagos (venta_id, importe, metodo) VALUES (?, ?, ?)",
                (venta_id, -p["total"], p["metodo"]),
            )
    motivo = request.form.get("motivo", "").strip()
    notas = venta["notas"] + (f"\nAnulada: {motivo}" if motivo else "")
    db.execute("UPDATE ventas SET estado = 'Anulada', notas = ? WHERE id = ?", (notas.strip(), venta_id))
    db.commit()
    flash("Venta anulada. Se ha repuesto el stock y registrado la devolución de lo cobrado.", "ok")
    return redirect(url_for("ventas.detalle", venta_id=venta_id))
