import csv
import io

from flask import Blueprint, Response, abort, flash, jsonify, redirect, render_template, request, url_for

from .constantes import CODIGO_ARMAZON_PROPIO, CATEGORIA_ARMAZON, CATEGORIAS, MEDIDAS_ARMAZON
from .db import get_db
from .utils import formato_importe, parse_entero, parse_importe

bp = Blueprint("productos", __name__, url_prefix="/productos")

CAMPOS_TEXTO = ["codigo", "categoria", "marca", "modelo", "color", "descripcion", "proveedor"]
CAMPOS_MEDIDAS = [campo for campo, _, _ in MEDIDAS_ARMAZON]


def obtener_producto(producto_id):
    producto = get_db().execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
    if producto is None:
        abort(404)
    return producto


def nombre_producto(p):
    partes = [p["marca"], p["modelo"], p["color"]]
    nombre = " ".join(x for x in partes if x)
    return nombre or p["descripcion"] or p["codigo"]


def registrar_movimiento(db, producto_id, cantidad, tipo, motivo="", venta_id=None):
    """Aplica un cambio de stock y lo deja anotado. Devuelve el stock resultante."""
    db.execute("UPDATE productos SET stock = stock + ? WHERE id = ?", (cantidad, producto_id))
    stock = db.execute("SELECT stock FROM productos WHERE id = ?", (producto_id,)).fetchone()["stock"]
    db.execute(
        "INSERT INTO movimientos_stock (producto_id, tipo, cantidad, stock_resultante, motivo, venta_id)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (producto_id, tipo, cantidad, stock, motivo, venta_id),
    )
    return stock


def consulta_productos(q="", categoria="", filtro="", incluir_inactivos=False):
    sql = "SELECT * FROM productos WHERE 1=1"
    params = []
    if not incluir_inactivos:
        sql += " AND activo = 1"
    if q:
        patron = f"%{q}%"
        sql += (
            " AND (codigo LIKE ? OR marca LIKE ? OR modelo LIKE ? OR color LIKE ?"
            " OR descripcion LIKE ? OR proveedor LIKE ?)"
        )
        params += [patron] * 6
    if categoria:
        sql += " AND categoria = ?"
        params.append(categoria)
    if filtro == "bajo":
        sql += " AND controla_stock = 1 AND stock <= stock_minimo"
    elif filtro == "agotado":
        sql += " AND controla_stock = 1 AND stock <= 0"
    sql += " ORDER BY categoria, marca COLLATE NOCASE, modelo COLLATE NOCASE"
    return get_db().execute(sql, params).fetchall()


@bp.route("/")
def lista():
    q = request.args.get("q", "").strip()
    categoria = request.args.get("categoria", "")
    filtro = request.args.get("filtro", "")
    inactivos = bool(request.args.get("inactivos"))
    productos = consulta_productos(q, categoria, filtro, inactivos)
    valor_coste = sum(p["precio_coste"] * max(p["stock"], 0) for p in productos if p["controla_stock"])
    valor_venta = sum(p["precio_venta"] * max(p["stock"], 0) for p in productos if p["controla_stock"])
    unidades = sum(max(p["stock"], 0) for p in productos if p["controla_stock"])
    return render_template(
        "productos/lista.html",
        productos=productos, categorias=CATEGORIAS, q=q, categoria=categoria,
        filtro=filtro, inactivos=inactivos,
        valor_coste=valor_coste, valor_venta=valor_venta, unidades=unidades,
    )


@bp.route("/exportar.csv")
def exportar():
    productos = consulta_productos(
        request.args.get("q", "").strip(), request.args.get("categoria", ""),
        request.args.get("filtro", ""), bool(request.args.get("inactivos")),
    )
    salida = io.StringIO()
    salida.write("﻿")  # BOM para que Excel detecte UTF-8
    w = csv.writer(salida, delimiter=";")
    w.writerow(["Código", "Categoría", "Marca", "Modelo", "Color", "Descripción", "Proveedor",
                "Precio coste", "Precio venta", "Stock", "Stock mínimo"])
    for p in productos:
        w.writerow([
            p["codigo"], p["categoria"], p["marca"], p["modelo"], p["color"], p["descripcion"],
            p["proveedor"], formato_importe(p["precio_coste"]), formato_importe(p["precio_venta"]),
            p["stock"] if p["controla_stock"] else "", p["stock_minimo"],
        ])
    return Response(
        salida.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=inventario.csv"},
    )


def datos_producto_formulario():
    datos = {c: request.form.get(c, "").strip() for c in CAMPOS_TEXTO}
    # Las medidas solo tienen sentido en los armazones
    es_armazon = datos["categoria"] == CATEGORIA_ARMAZON
    for campo in CAMPOS_MEDIDAS:
        datos[campo] = request.form.get(campo, "").strip() if es_armazon else ""
    errores = []
    if not datos["codigo"]:
        errores.append("El código es obligatorio.")
    if datos["categoria"] not in CATEGORIAS:
        errores.append("Selecciona una categoría.")
    try:
        datos["precio_coste"] = parse_importe(request.form.get("precio_coste"))
        datos["precio_venta"] = parse_importe(request.form.get("precio_venta"))
        datos["stock_minimo"] = parse_entero(request.form.get("stock_minimo"))
    except ValueError as e:
        errores.append(str(e))
    datos["controla_stock"] = 1 if request.form.get("controla_stock") else 0
    return datos, errores


def codigo_duplicado(codigo, excluir_id=None):
    fila = get_db().execute(
        "SELECT id FROM productos WHERE codigo = ? AND id != ?", (codigo, excluir_id or 0)
    ).fetchone()
    return fila is not None


def contexto_form(producto):
    """Prepara el producto para el formulario, con los importes como texto."""
    form = dict(producto)
    for campo in ("precio_coste", "precio_venta"):
        if isinstance(form.get(campo), int):
            form[campo] = formato_importe(form[campo])
    return {"producto": form, "categorias": CATEGORIAS,
            "medidas": MEDIDAS_ARMAZON, "armazon": CATEGORIA_ARMAZON}


def producto_para_form(datos):
    """Vuelve a mostrar los importes tal y como se escribieron si hay errores."""
    form = dict(datos)
    for campo in ("precio_coste", "precio_venta"):
        form[campo] = request.form.get(campo, "")
    return form


@bp.route("/nuevo", methods=["GET", "POST"])
def nuevo():
    if request.method == "POST":
        datos, errores = datos_producto_formulario()
        if not errores and codigo_duplicado(datos["codigo"]):
            errores.append("Ya existe un producto con ese código.")
        try:
            stock_inicial = parse_entero(request.form.get("stock"))
        except ValueError as e:
            errores.append(str(e))
            stock_inicial = 0
        if errores:
            for e in errores:
                flash(e, "error")
            form = producto_para_form(datos)
            form["stock"] = request.form.get("stock", "")
            return render_template("productos/form.html", **contexto_form(form))
        db = get_db()
        columnas = list(datos.keys())
        cur = db.execute(
            f"INSERT INTO productos ({', '.join(columnas)}) VALUES ({', '.join('?' * len(columnas))})",
            list(datos.values()),
        )
        if stock_inicial and datos["controla_stock"]:
            registrar_movimiento(db, cur.lastrowid, stock_inicial, "entrada", "Stock inicial")
        db.commit()
        flash("Producto creado.", "ok")
        return redirect(url_for("productos.detalle", producto_id=cur.lastrowid))
    return render_template(
        "productos/form.html",
        **contexto_form({"categoria": request.args.get("categoria", ""), "controla_stock": 1}),
    )


@bp.route("/<int:producto_id>/editar", methods=["GET", "POST"])
def editar(producto_id):
    producto = obtener_producto(producto_id)
    if request.method == "POST":
        datos, errores = datos_producto_formulario()
        if not errores and codigo_duplicado(datos["codigo"], producto_id):
            errores.append("Ya existe un producto con ese código.")
        if errores:
            for e in errores:
                flash(e, "error")
            form = producto_para_form(datos)
            form["id"] = producto_id
            form["stock"] = producto["stock"]
            return render_template("productos/form.html", **contexto_form(form))
        db = get_db()
        db.execute(
            f"UPDATE productos SET {', '.join(f'{c} = ?' for c in datos)} WHERE id = ?",
            [*datos.values(), producto_id],
        )
        db.commit()
        flash("Producto guardado.", "ok")
        return redirect(url_for("productos.detalle", producto_id=producto_id))
    return render_template("productos/form.html", **contexto_form(producto))


@bp.route("/<int:producto_id>")
def detalle(producto_id):
    producto = obtener_producto(producto_id)
    movimientos = get_db().execute(
        """
        SELECT m.*, v.numero AS venta_numero FROM movimientos_stock m
        LEFT JOIN ventas v ON v.id = m.venta_id
        WHERE m.producto_id = ? ORDER BY m.id DESC LIMIT 200
        """,
        (producto_id,),
    ).fetchall()
    return render_template(
        "productos/detalle.html", producto=producto, movimientos=movimientos,
        nombre=nombre_producto(producto), medidas=MEDIDAS_ARMAZON, armazon=CATEGORIA_ARMAZON,
    )


@bp.route("/<int:producto_id>/movimiento", methods=["POST"])
def movimiento(producto_id):
    producto = obtener_producto(producto_id)
    tipo = request.form.get("tipo")
    motivo = request.form.get("motivo", "").strip()
    try:
        cantidad = parse_entero(request.form.get("cantidad"))
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("productos.detalle", producto_id=producto_id))
    db = get_db()
    if tipo == "entrada":
        if cantidad <= 0:
            flash("La cantidad de entrada debe ser mayor que cero.", "error")
            return redirect(url_for("productos.detalle", producto_id=producto_id))
        registrar_movimiento(db, producto_id, cantidad, "entrada", motivo or "Entrada de mercancía")
        flash(f"Entrada de {cantidad} uds. registrada.", "ok")
    elif tipo == "recuento":
        if cantidad < 0:
            flash("El recuento no puede ser negativo.", "error")
            return redirect(url_for("productos.detalle", producto_id=producto_id))
        diferencia = cantidad - producto["stock"]
        if diferencia:
            registrar_movimiento(db, producto_id, diferencia, "ajuste", motivo or "Recuento de inventario")
        flash(f"Stock ajustado a {cantidad} uds.", "ok")
    else:
        abort(400)
    db.commit()
    return redirect(url_for("productos.detalle", producto_id=producto_id))


@bp.route("/<int:producto_id>/activo", methods=["POST"])
def cambiar_activo(producto_id):
    producto = obtener_producto(producto_id)
    db = get_db()
    db.execute("UPDATE productos SET activo = ? WHERE id = ?", (0 if producto["activo"] else 1, producto_id))
    db.commit()
    flash("Producto dado de baja." if producto["activo"] else "Producto reactivado.", "ok")
    return redirect(url_for("productos.detalle", producto_id=producto_id))


@bp.route("/api/buscar")
def api_buscar():
    q = request.args.get("q", "").strip()
    productos = consulta_productos(q)[:20] if q else []
    return jsonify([
        {
            "id": p["id"], "codigo": p["codigo"], "categoria": p["categoria"],
            "nombre": nombre_producto(p), "precio": p["precio_venta"],
            "stock": p["stock"], "controla_stock": bool(p["controla_stock"]),
            "armazon_propio": p["codigo"] == CODIGO_ARMAZON_PROPIO,
        }
        for p in productos
    ])
