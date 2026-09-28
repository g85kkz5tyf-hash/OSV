from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .constantes import CATEGORIA_LENTE, PRECIO_RANURADO, CODIGO_ARMAZON_PROPIO, COLORES_EJECUCION, LABORATORIOS, TALLER_PROPIO, CAMPOS_OJO, CATEGORIA_ARMAZON, MEDIDAS_ARMAZON, ESTADOS_ABIERTOS, ESTADOS_VENTA, METODOS_PAGO
from .db import get_config, get_db
from .productos import nombre_producto, registrar_movimiento
from .utils import importe_linea, parse_entero, parse_importe

bp = Blueprint("ventas", __name__, url_prefix="/ventas")

SQL_VENTAS = """
    SELECT v.*,
           COALESCE((SELECT SUM(importe) FROM pagos WHERE venta_id = v.id), 0) AS pagado,
           TRIM(COALESCE(c.nombre, '') || ' ' || COALESCE(c.apellidos, '')) AS cliente_nombre
    FROM ventas v LEFT JOIN clientes c ON c.id = v.cliente_id
"""


class ErrorVenta(Exception):
    pass


def leer_ejecucion(form):
    """Dónde se hace el trabajo: «Taller propio», el laboratorio elegido o '' si no aplica."""
    lugar = form.get("lugar", "")
    if lugar == "taller":
        return TALLER_PROPIO
    if lugar == "laboratorio":
        laboratorio = form.get("laboratorio", "")
        if laboratorio not in LABORATORIOS:
            raise ErrorVenta("Elige en qué laboratorio se arma el trabajo.")
        return laboratorio
    return ""


def leer_pagos(form, campo_importe):
    """Lee uno o varios cobros (importe + medio de pago). Devuelve [(importe, metodo)]."""
    importes = form.getlist(campo_importe)
    metodos = form.getlist("metodo")
    pagos = []
    for i, texto in enumerate(importes):
        try:
            importe = parse_importe(texto)
        except ValueError as e:
            raise ErrorVenta(str(e))
        if importe == 0:
            continue
        if importe < 0:
            raise ErrorVenta("El importe cobrado no puede ser negativo.")
        metodo = metodos[i] if i < len(metodos) else ""
        if metodo not in METODOS_PAGO:
            raise ErrorVenta("Medio de pago no válido.")
        pagos.append((importe, metodo))
    return pagos


def destino_seguro(volver, defecto):
    """Solo se vuelve a páginas del propio programa."""
    return volver if volver.startswith("/") and not volver.startswith("//") else defecto


def contexto_ejecucion():
    return {"laboratorios": LABORATORIOS, "taller_propio": TALLER_PROPIO, "colores": COLORES_EJECUCION}


def recetas_de_venta(db, venta):
    recetas = db.execute(
        "SELECT r.* FROM venta_recetas vr JOIN recetas r ON r.id = vr.receta_id"
        " WHERE vr.venta_id = ? ORDER BY vr.orden",
        (venta["id"],),
    ).fetchall()
    if not recetas and venta["receta_id"]:
        recetas = db.execute("SELECT * FROM recetas WHERE id = ?", (venta["receta_id"],)).fetchall()
    return recetas


def trabajos_por_receta(db, venta_ids):
    """{venta_id: [receta_id, tipo, fecha, numero_trabajo]} de las ventas con más de una receta."""
    if not venta_ids:
        return {}
    filas = db.execute(
        f"""SELECT vr.venta_id, vr.receta_id, vr.numero_trabajo, r.tipo, r.fecha
            FROM venta_recetas vr JOIN recetas r ON r.id = vr.receta_id
            WHERE vr.venta_id IN ({', '.join('?' * len(venta_ids))}) ORDER BY vr.venta_id, vr.orden""",
        list(venta_ids),
    ).fetchall()
    resultado = {}
    for f in filas:
        resultado.setdefault(f["venta_id"], []).append(f)
    return {v: filas for v, filas in resultado.items() if len(filas) > 1}


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


# Datos que se guardan en la línea «Armazón propio»: medidas y si va ranurado
CAMPOS_ARMAZON_PROPIO = [campo for campo, _, _ in MEDIDAS_ARMAZON] + ["ranurado"]


def es_armazon_propio(producto):
    return producto is not None and producto["codigo"] == CODIGO_ARMAZON_PROPIO


def leer_lineas_formulario(db, receta_ids=()):
    """Lee las líneas enviadas por el formulario y las valida contra el stock.

    receta_ids: recetas asociadas a la venta. Cada producto de cristales queda ligado a una de ellas.
    """
    f = request.form
    recetas_linea = f.getlist("linea_receta")
    producto_ids = f.getlist("producto_id")
    descripciones = f.getlist("descripcion")
    cantidades = f.getlist("cantidad")
    precios = f.getlist("precio")
    descuentos = f.getlist("descuento")
    # Medidas del armazón propio: cada línea envía sus cuatro campos (vacíos si no aplica)
    medidas = {campo: f.getlist(f"medida_{campo}") for campo in CAMPOS_ARMAZON_PROPIO}
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
            if not descripcion:
                descripcion = nombre_producto(producto)
            if producto["controla_stock"]:
                necesidades[producto["id"]] = necesidades.get(producto["id"], 0) + cantidad
                if necesidades[producto["id"]] > producto["stock"]:
                    raise ErrorVenta(
                        f"No hay stock suficiente de «{descripcion}» "
                        f"(disponible: {producto['stock']}, solicitado: {necesidades[producto['id']]})."
                    )
        receta_linea = None
        if producto is not None and producto["categoria"] == CATEGORIA_LENTE and receta_ids:
            if len(receta_ids) == 1:
                receta_linea = receta_ids[0]
            else:
                elegida = recetas_linea[i] if i < len(recetas_linea) else ""
                if not elegida.isdigit() or int(elegida) not in receta_ids:
                    raise ErrorVenta(f"Elige a qué receta corresponde «{descripcion}».")
                receta_linea = int(elegida)
        lineas.append({
            "producto": producto,
            "descripcion": descripcion,
            "cantidad": cantidad,
            "precio_unitario": precio,
            "descuento_pct": descuento,
            "importe": importe_linea(cantidad, precio, descuento),
            "receta_id": receta_linea,
            **{campo: (valores[i].strip() if i < len(valores) and es_armazon_propio(producto) else "")
               for campo, valores in medidas.items()},
        })
    if not lineas:
        raise ErrorVenta("Añade al menos una línea a la venta.")
    return lineas


def crear_venta(db, cliente_id, receta_ids, lineas, estado, entrega_prevista, notas, pagos,
                ejecucion=""):
    receta_id = receta_ids[0] if receta_ids else None  # la principal
    total = sum(l["importe"] for l in lineas)
    if sum(importe for importe, _ in pagos) > total:
        raise ErrorVenta("El importe cobrado no puede superar el total de la venta.")
    numero = siguiente_numero(db)
    cur = db.execute(
        "INSERT INTO ventas (numero, cliente_id, receta_id, total, estado, fecha_entrega_prevista, notas,"
        " ejecucion) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (numero, cliente_id, receta_id, total, estado, entrega_prevista, notas, ejecucion),
    )
    venta_id = cur.lastrowid
    for orden, rid in enumerate(receta_ids):
        db.execute("INSERT INTO venta_recetas (venta_id, receta_id, orden) VALUES (?, ?, ?)", (venta_id, rid, orden))
    for l in lineas:
        producto = l["producto"]
        db.execute(
            "INSERT INTO lineas_venta (venta_id, producto_id, descripcion, cantidad, precio_unitario,"
            " descuento_pct, iva, importe, calibre, puente, diagonal, altura, ranurado, receta_id)"
            " VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)",
            (venta_id, producto["id"] if producto else None, l["descripcion"], l["cantidad"],
             l["precio_unitario"], l["descuento_pct"], l["importe"],
             l["calibre"], l["puente"], l["diagonal"], l["altura"], l["ranurado"], l["receta_id"]),
        )
        if producto and producto["controla_stock"]:
            registrar_movimiento(db, producto["id"], -l["cantidad"], "venta", f"Venta {numero}", venta_id)
    for importe, metodo in pagos:
        db.execute(
            "INSERT INTO pagos (venta_id, importe, metodo) VALUES (?, ?, ?)", (venta_id, importe, metodo)
        )
    return venta_id


@bp.route("/nueva", methods=["GET", "POST"])
def nueva():
    db = get_db()
    if request.method == "POST":
        f = request.form
        cliente_id = parse_entero(f.get("cliente_id"), None) if f.get("cliente_id", "").isdigit() else None
        # Una o varias recetas (sin repetir y en el orden elegido)
        receta_ids = list(dict.fromkeys(int(r) for r in f.getlist("receta_id") if r.isdigit()))
        estado = f.get("estado", "Entregado")
        try:
            if estado not in ESTADOS_VENTA or estado == "Anulada":
                raise ErrorVenta("Estado no válido.")
            if cliente_id and not db.execute("SELECT 1 FROM clientes WHERE id = ?", (cliente_id,)).fetchone():
                raise ErrorVenta("El cliente no existe.")
            for rid in receta_ids:
                if not db.execute(
                    "SELECT 1 FROM recetas WHERE id = ? AND cliente_id IS ?", (rid, cliente_id)
                ).fetchone():
                    raise ErrorVenta("La receta no pertenece al cliente seleccionado.")
            pagos = leer_pagos(f, "pago")
            ejecucion = leer_ejecucion(f)
            lineas = leer_lineas_formulario(db, receta_ids)
            venta_id = crear_venta(
                db, cliente_id, receta_ids, lineas, estado,
                f.get("fecha_entrega_prevista", "").strip(), f.get("notas", "").strip(), pagos,
                ejecucion,
            )
        except ErrorVenta as e:
            db.rollback()
            flash(str(e), "error")
            return render_template("ventas/nueva.html", **contexto_nueva(request.form))
        db.commit()
        flash("Venta registrada.", "ok")
        if f.get("accion") == "orden":
            return redirect(url_for("ventas.orden", venta_id=venta_id))
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
    propio = db.execute("SELECT id FROM productos WHERE codigo = ?", (CODIGO_ARMAZON_PROPIO,)).fetchone()
    if form:
        for i, descripcion in enumerate(form.getlist("descripcion")):
            medidas = {campo: (form.getlist(f"medida_{campo}")[i:i + 1] or [""])[0] for campo in CAMPOS_ARMAZON_PROPIO}
            producto_id = form.getlist("producto_id")[i]
            categoria = ""
            if producto_id.isdigit():
                fila = db.execute("SELECT categoria FROM productos WHERE id = ?", (producto_id,)).fetchone()
                categoria = fila["categoria"] if fila else ""
            lineas.append({
                "categoria": categoria,
                "linea_receta": (form.getlist("linea_receta")[i:i + 1] or [""])[0],
                "armazon_propio": bool(propio) and producto_id == str(propio["id"]),
                **medidas,
                "producto_id": form.getlist("producto_id")[i],
                "descripcion": descripcion,
                "cantidad": form.getlist("cantidad")[i],
                "precio": form.getlist("precio")[i],
                "descuento": form.getlist("descuento")[i],
            })
    if form:
        recetas_elegidas = [r for r in form.getlist("receta_id") if r]
    else:
        recetas_elegidas = [str(recetas[0]["id"])] if recetas else []
    return {
        "cliente": cliente, "form": form or {}, "lineas": lineas,
        "recetas": [{"id": r["id"], "fecha": r["fecha"], "tipo": r["tipo"]} for r in recetas],
        "recetas_elegidas": recetas_elegidas, "categoria_lente": CATEGORIA_LENTE,
        "estados": [e for e in ESTADOS_VENTA if e != "Anulada"], "metodos": METODOS_PAGO,
        **contexto_ejecucion(), "medidas": MEDIDAS_ARMAZON,
        "precio_ranurado": PRECIO_RANURADO,
        "cobros": list(zip(form.getlist("pago"), form.getlist("metodo"))) if form else [("", METODOS_PAGO[0])],
    }


@bp.route("/<int:venta_id>")
def detalle(venta_id):
    db = get_db()
    venta = obtener_venta(venta_id)
    lineas = db.execute(
        "SELECT l.*, p.codigo = ? AS armazon_propio FROM lineas_venta l"
        " LEFT JOIN productos p ON p.id = l.producto_id WHERE l.venta_id = ? ORDER BY l.id",
        (CODIGO_ARMAZON_PROPIO, venta_id),
    ).fetchall()
    pagos = db.execute("SELECT * FROM pagos WHERE venta_id = ? ORDER BY id", (venta_id,)).fetchall()
    cliente = None
    if venta["cliente_id"]:
        cliente = db.execute("SELECT * FROM clientes WHERE id = ?", (venta["cliente_id"],)).fetchone()
    recetas = recetas_de_venta(db, venta)
    return render_template(
        "ventas/detalle.html", venta=venta, lineas=lineas, pagos=pagos, cliente=cliente,
        recetas=recetas, estados=[e for e in ESTADOS_VENTA if e != "Anulada"], metodos=METODOS_PAGO,
        campos_ojo=CAMPOS_OJO, **contexto_ejecucion(),
        trabajos=trabajos_por_receta(db, [venta_id]).get(venta_id, []),
        medidas=MEDIDAS_ARMAZON, precio_ranurado=PRECIO_RANURADO,
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
        config=get_config(db),
    )


@bp.route("/<int:venta_id>/orden")
def orden(venta_id):
    """Orden de trabajo en A4 para imprimir, con recuadros de seña y saldo a mano."""
    db = get_db()
    venta = obtener_venta(venta_id)
    lineas = db.execute(
        "SELECT l.id, l.descripcion, l.cantidad, l.descuento_pct, l.importe, l.receta_id, p.categoria,"
        + ", ".join(
            f" CASE WHEN p.codigo = :propio THEN l.{c} ELSE p.{c} END AS {c}" for c, _, _ in MEDIDAS_ARMAZON
        )
        + ", CASE WHEN p.codigo = :propio THEN l.ranurado ELSE '' END AS ranurado"
        " FROM lineas_venta l LEFT JOIN productos p ON p.id = l.producto_id"
        " WHERE l.venta_id = :venta ORDER BY l.id",
        {"propio": CODIGO_ARMAZON_PROPIO, "venta": venta_id},
    ).fetchall()
    cliente = None
    if venta["cliente_id"]:
        cliente = db.execute("SELECT * FROM clientes WHERE id = ?", (venta["cliente_id"],)).fetchone()
    recetas = recetas_de_venta(db, venta)
    return render_template(
        "ventas/orden.html", venta=venta, lineas=lineas, cliente=cliente, recetas=recetas,
        campos_ojo=CAMPOS_OJO, config=get_config(db),
        medidas=MEDIDAS_ARMAZON, armazon=CATEGORIA_ARMAZON,
        color_ejecucion=COLORES_EJECUCION.get(venta["ejecucion"], ""),
    )


@bp.route("/<int:venta_id>/pago", methods=["POST"])
def pago(venta_id):
    venta = obtener_venta(venta_id)
    volver = destino_seguro(request.form.get("volver", ""), url_for("ventas.detalle", venta_id=venta_id))
    if venta["estado"] == "Anulada":
        abort(400)
    try:
        pagos = leer_pagos(request.form, "importe")
    except ErrorVenta as e:
        flash(str(e), "error")
        return redirect(volver)
    pendiente = venta["total"] - venta["pagado"]
    cobrado = sum(importe for importe, _ in pagos)
    if not pagos or cobrado > pendiente:
        flash("El importe debe ser mayor que cero y no superar lo pendiente.", "error")
    else:
        db = get_db()
        for importe, metodo in pagos:
            db.execute("INSERT INTO pagos (venta_id, importe, metodo) VALUES (?, ?, ?)", (venta_id, importe, metodo))
        db.commit()
        flash(("Cobro registrado" if len(pagos) == 1 else f"{len(pagos)} cobros registrados")
              + f" en la venta {venta['numero']}.", "ok")
    return redirect(volver)


@bp.route("/<int:venta_id>/estado", methods=["POST"])
def estado(venta_id):
    venta = obtener_venta(venta_id)
    nuevo = request.form.get("estado")
    if venta["estado"] == "Anulada" or nuevo not in ESTADOS_VENTA or nuevo == "Anulada":
        abort(400)
    try:
        ejecucion = leer_ejecucion(request.form)
    except ErrorVenta as e:
        flash(str(e), "error")
        return redirect(url_for("ventas.detalle", venta_id=venta_id))
    numero = request.form.get("numero_trabajo", "").strip() if ejecucion in LABORATORIOS else ""
    db = get_db()
    for r in trabajos_por_receta(db, [venta_id]).get(venta_id, []):
        valor = request.form.get(f"numero_trabajo_{r['receta_id']}", r["numero_trabajo"]).strip()
        db.execute("UPDATE venta_recetas SET numero_trabajo = ? WHERE venta_id = ? AND receta_id = ?",
                   (valor if ejecucion in LABORATORIOS else "", venta_id, r["receta_id"]))
    db.execute(
        "UPDATE ventas SET estado = ?, fecha_entrega_prevista = ?, notas = ?, ejecucion = ?,"
        " numero_trabajo = ? WHERE id = ?",
        (nuevo, request.form.get("fecha_entrega_prevista", "").strip(),
         request.form.get("notas", "").strip(), ejecucion, numero, venta_id),
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
    return redirect(destino_seguro(request.form.get("volver", ""), url_for("main.inicio")))


@bp.route("/<int:venta_id>/medidas/<int:linea_id>", methods=["POST"])
def medidas_armazon_propio(venta_id, linea_id):
    """Cargar o corregir las medidas del armazón que trajo el cliente."""
    venta = obtener_venta(venta_id)
    volver = destino_seguro(request.form.get("volver", ""), url_for("ventas.detalle", venta_id=venta_id))
    db = get_db()
    linea = db.execute(
        "SELECT l.* FROM lineas_venta l JOIN productos p ON p.id = l.producto_id"
        " WHERE l.id = ? AND l.venta_id = ? AND p.codigo = ?",
        (linea_id, venta_id, CODIGO_ARMAZON_PROPIO),
    ).fetchone()
    if linea is None:
        abort(404)
    ranurado = "1" if request.form.get("ranurado") else ""
    precio = linea["precio_unitario"]
    if ranurado != linea["ranurado"] and venta["estado"] != "Anulada":
        # Marcar o desmarcar «Ranurado» cambia el precio de la línea y el total de la venta
        precio = PRECIO_RANURADO if ranurado else 0
        importe = importe_linea(linea["cantidad"], precio, linea["descuento_pct"])
        nuevo_total = venta["total"] - linea["importe"] + importe
        if nuevo_total < venta["pagado"]:
            flash("No se puede quitar el ranurado: lo ya cobrado superaría el nuevo total.", "error")
            return redirect(volver)
        db.execute("UPDATE lineas_venta SET precio_unitario = ?, importe = ? WHERE id = ?", (precio, importe, linea_id))
        db.execute("UPDATE ventas SET total = ? WHERE id = ?", (nuevo_total, venta_id))
    elif venta["estado"] == "Anulada":
        ranurado = linea["ranurado"]
    campos = [c for c, _, _ in MEDIDAS_ARMAZON]
    db.execute(
        f"UPDATE lineas_venta SET {', '.join(f'{c} = ?' for c in campos)}, ranurado = ? WHERE id = ?",
        [*(request.form.get(c, "").strip() for c in campos), ranurado, linea_id],
    )
    db.commit()
    flash("Armazón propio actualizado.", "ok")
    return redirect(volver)


@bp.route("/<int:venta_id>/numero-trabajo", methods=["POST"])
def numero_trabajo(venta_id):
    """Guarda el número de trabajo que asigna el laboratorio."""
    venta = obtener_venta(venta_id)
    volver = destino_seguro(request.form.get("volver", ""), url_for("ventas.detalle", venta_id=venta_id))
    numero = request.form.get("numero_trabajo", "").strip()
    db = get_db()
    varias = trabajos_por_receta(db, [venta_id]).get(venta_id)
    if venta["ejecucion"] not in LABORATORIOS:
        flash("Esta venta no se ejecuta en un laboratorio.", "error")
    elif not numero:
        flash("Escribe el número de trabajo.", "error")
    elif varias:
        # Varias recetas: el número es de una de ellas (lejos, cerca…)
        receta = next((r for r in varias if str(r["receta_id"]) == request.form.get("receta_id", "")), None)
        if receta is None:
            flash("Elige a qué receta corresponde el número de trabajo.", "error")
        else:
            db.execute("UPDATE venta_recetas SET numero_trabajo = ? WHERE venta_id = ? AND receta_id = ?",
                       (numero, venta_id, receta["receta_id"]))
            db.commit()
            flash(f"Venta {venta['numero']}: número de trabajo {numero} ({venta['ejecucion']}, "
                  f"receta {receta['tipo']}) guardado.", "ok")
    else:
        db.execute("UPDATE ventas SET numero_trabajo = ? WHERE id = ?", (numero, venta_id))
        db.commit()
        flash(f"Venta {venta['numero']}: número de trabajo {numero} ({venta['ejecucion']}) guardado.", "ok")
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
