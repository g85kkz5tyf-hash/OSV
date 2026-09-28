import sqlite3
import tempfile
from datetime import date, timedelta
from pathlib import Path

from flask import (Blueprint, current_app, flash, redirect, render_template, request,
                   send_file, url_for)

from .constantes import ESTADOS_ABIERTOS, METODOS_PAGO
from .db import get_config, get_db, set_config

bp = Blueprint("main", __name__)

CAMPOS_CONFIG = ["nombre", "nif", "direccion", "telefono", "email", "pie_ticket"]


@bp.route("/")
def inicio():
    db = get_db()
    hoy = date.today()
    inicio_mes = hoy.replace(day=1).isoformat()

    def suma_ventas(desde):
        return db.execute(
            "SELECT COALESCE(SUM(total), 0) AS total, COUNT(*) AS n FROM ventas"
            " WHERE estado != 'Anulada' AND date(fecha) >= ?",
            (desde,),
        ).fetchone()

    ventas_hoy = suma_ventas(hoy.isoformat())
    ventas_mes = suma_ventas(inicio_mes)
    cobrado_hoy = db.execute(
        "SELECT COALESCE(SUM(importe), 0) FROM pagos WHERE date(fecha) = ?", (hoy.isoformat(),)
    ).fetchone()[0]
    encargos = db.execute(
        f"""
        SELECT v.*, TRIM(COALESCE(c.nombre, '') || ' ' || COALESCE(c.apellidos, '')) AS cliente_nombre,
               c.telefono AS cliente_telefono,
               COALESCE((SELECT SUM(importe) FROM pagos WHERE venta_id = v.id), 0) AS pagado
        FROM ventas v LEFT JOIN clientes c ON c.id = v.cliente_id
        WHERE v.estado IN ({', '.join('?' * len(ESTADOS_ABIERTOS))})
        ORDER BY CASE v.fecha_entrega_prevista WHEN '' THEN 1 ELSE 0 END,
                 v.fecha_entrega_prevista, v.fecha
        """,
        ESTADOS_ABIERTOS,
    ).fetchall()
    pendiente_cobro = db.execute(
        """
        SELECT COALESCE(SUM(v.total - COALESCE((SELECT SUM(importe) FROM pagos WHERE venta_id = v.id), 0)), 0)
        FROM ventas v WHERE v.estado != 'Anulada'
        """
    ).fetchone()[0]
    stock_bajo = db.execute(
        "SELECT * FROM productos WHERE activo = 1 AND controla_stock = 1 AND stock <= stock_minimo"
        " ORDER BY stock, marca LIMIT 15"
    ).fetchall()
    revisiones = db.execute(
        """
        SELECT r.proxima_revision, r.tipo, c.id AS cliente_id, c.nombre, c.apellidos, c.telefono
        FROM recetas r JOIN clientes c ON c.id = r.cliente_id
        WHERE r.proxima_revision != '' AND r.proxima_revision BETWEEN ? AND ?
          AND r.id = (SELECT id FROM recetas r2 WHERE r2.cliente_id = r.cliente_id
                      ORDER BY r2.fecha DESC, r2.id DESC LIMIT 1)
        ORDER BY r.proxima_revision LIMIT 15
        """,
        ((hoy - timedelta(days=30)).isoformat(), (hoy + timedelta(days=30)).isoformat()),
    ).fetchall()
    return render_template(
        "inicio.html", ventas_hoy=ventas_hoy, ventas_mes=ventas_mes, cobrado_hoy=cobrado_hoy,
        encargos=encargos, pendiente_cobro=pendiente_cobro, stock_bajo=stock_bajo,
        revisiones=revisiones, hoy=hoy.isoformat(),
    )


@bp.route("/caja")
def caja():
    db = get_db()
    dia = request.args.get("dia") or date.today().isoformat()
    pagos = db.execute(
        """
        SELECT p.*, v.numero, v.id AS venta_id,
               TRIM(COALESCE(c.nombre, '') || ' ' || COALESCE(c.apellidos, '')) AS cliente_nombre
        FROM pagos p JOIN ventas v ON v.id = p.venta_id LEFT JOIN clientes c ON c.id = v.cliente_id
        WHERE date(p.fecha) = ? ORDER BY p.fecha, p.id
        """,
        (dia,),
    ).fetchall()
    por_metodo = {m: 0 for m in METODOS_PAGO}
    for p in pagos:
        por_metodo[p["metodo"]] = por_metodo.get(p["metodo"], 0) + p["importe"]
    return render_template(
        "caja.html", dia=dia, pagos=pagos, por_metodo=por_metodo,
        total=sum(p["importe"] for p in pagos),
    )


@bp.route("/informes")
def informes():
    db = get_db()
    anio = request.args.get("anio") or str(date.today().year)
    meses = db.execute(
        """
        SELECT strftime('%m', fecha) AS mes, COUNT(*) AS n, SUM(total) AS total
        FROM ventas WHERE estado != 'Anulada' AND strftime('%Y', fecha) = ?
        GROUP BY mes ORDER BY mes
        """,
        (anio,),
    ).fetchall()
    categorias = db.execute(
        """
        SELECT COALESCE(p.categoria, 'Sin producto') AS categoria,
               SUM(l.cantidad) AS unidades, SUM(l.importe) AS total
        FROM lineas_venta l JOIN ventas v ON v.id = l.venta_id
        LEFT JOIN productos p ON p.id = l.producto_id
        WHERE v.estado != 'Anulada' AND strftime('%Y', v.fecha) = ?
        GROUP BY 1 ORDER BY total DESC
        """,
        (anio,),
    ).fetchall()
    top = db.execute(
        """
        SELECT l.descripcion, SUM(l.cantidad) AS unidades, SUM(l.importe) AS total
        FROM lineas_venta l JOIN ventas v ON v.id = l.venta_id
        WHERE v.estado != 'Anulada' AND strftime('%Y', v.fecha) = ? AND l.producto_id IS NOT NULL
        GROUP BY l.producto_id ORDER BY unidades DESC, total DESC LIMIT 10
        """,
        (anio,),
    ).fetchall()
    anios = [r[0] for r in db.execute(
        "SELECT DISTINCT strftime('%Y', fecha) FROM ventas ORDER BY 1 DESC"
    )] or [anio]
    if anio not in anios:
        anios.insert(0, anio)
    nombres_mes = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
                   "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    datos_mes = {m["mes"]: m for m in meses}
    filas_mes = [
        {"nombre": nombres_mes[i], "n": datos_mes.get(f"{i + 1:02d}", {"n": 0})["n"],
         "total": datos_mes.get(f"{i + 1:02d}", {"total": 0})["total"] or 0}
        for i in range(12)
    ]
    return render_template(
        "informes.html", anio=anio, anios=anios, filas_mes=filas_mes, categorias=categorias,
        top=top, total_anio=sum(f["total"] for f in filas_mes),
        max_mes=max([f["total"] for f in filas_mes] + [1]),
    )


@bp.route("/configuracion", methods=["GET", "POST"])
def configuracion():
    db = get_db()
    if request.method == "POST":
        set_config(db, {c: request.form.get(c, "").strip() for c in CAMPOS_CONFIG})
        db.commit()
        flash("Configuración guardada.", "ok")
        return redirect(url_for("main.configuracion"))
    return render_template("configuracion.html", config=get_config(db))


@bp.route("/copia-seguridad")
def copia_seguridad():
    """Descarga una copia consistente de la base de datos."""
    destino = Path(tempfile.mkdtemp()) / f"optica-{date.today().isoformat()}.db"
    origen = sqlite3.connect(current_app.config["DATABASE"])
    copia = sqlite3.connect(destino)
    with copia:
        origen.backup(copia)
    origen.close()
    copia.close()
    return send_file(destino, as_attachment=True, download_name=destino.name)
