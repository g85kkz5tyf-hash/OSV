import json
import os
import sqlite3
import tempfile
import threading
from datetime import date
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, redirect, render_template, request,
                   send_file, url_for)

from .constantes import LABORATORIOS, TALLER_PROPIO, ESTADOS_ABIERTOS, ESTADOS_VENTA, METODOS_PAGO
from .db import get_config, get_db, set_config
from .utils import formato_fecha, parse_importe
from .ventas import trabajos_por_receta

bp = Blueprint("main", __name__)

MARCA_ESTADO = "gestion-optica-ok"

CAMPOS_CONFIG = ["nombre", "nif", "direccion", "telefono", "email", "pie_ticket"]


@bp.route("/estado")
def estado():
    """Permite al lanzador comprobar que en el puerto está este programa y no otro."""
    return MARCA_ESTADO


@bp.route("/cerrar", methods=["POST"])
def cerrar():
    """El lanzador cierra la copia que ya estaba abierta para arrancar la versión nueva."""
    clave = current_app.config.get("CLAVE_CIERRE")
    if not clave or request.form.get("clave") != clave:
        abort(403)
    threading.Timer(0.3, lambda: os._exit(0)).start()
    return "cerrando"


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
    # Trabajos cuya fecha de entrega prevista ya pasó y todavía no están listos
    atrasados = db.execute(
        """
        SELECT v.id, v.numero, v.estado, v.fecha_entrega_prevista, v.ejecucion, v.numero_trabajo,
               TRIM(COALESCE(c.nombre, '') || ' ' || COALESCE(c.apellidos, '')) AS cliente_nombre,
               c.telefono AS cliente_telefono
        FROM ventas v LEFT JOIN clientes c ON c.id = v.cliente_id
        WHERE v.estado IN ('Pendiente', 'En taller')
          AND v.fecha_entrega_prevista != '' AND v.fecha_entrega_prevista < ?
        ORDER BY v.fecha_entrega_prevista, v.id
        """,
        (hoy.isoformat(),),
    ).fetchall()
    # Trabajos del taller propio que aún no están listos para recoger
    tareas = db.execute(
        """
        SELECT v.id, v.numero, v.estado, v.fecha_entrega_prevista, v.cliente_id,
               TRIM(COALESCE(c.nombre, '') || ' ' || COALESCE(c.apellidos, '')) AS cliente_nombre,
               (SELECT GROUP_CONCAT(descripcion, ' · ') FROM lineas_venta WHERE venta_id = v.id) AS articulos
        FROM ventas v LEFT JOIN clientes c ON c.id = v.cliente_id
        WHERE v.ejecucion = ? AND v.estado IN ('Pendiente', 'En taller')
        ORDER BY CASE v.fecha_entrega_prevista WHEN '' THEN 1 ELSE 0 END,
                 v.fecha_entrega_prevista, v.fecha
        """,
        (TALLER_PROPIO,),
    ).fetchall()
    return render_template(
        "inicio.html", ventas_hoy=ventas_hoy, ventas_mes=ventas_mes, cobrado_hoy=cobrado_hoy,
        encargos=encargos, pendiente_cobro=pendiente_cobro, stock_bajo=stock_bajo,
        tareas=tareas, atrasados=atrasados, hoy=hoy.isoformat(),
        trabajos=trabajos_por_receta(db, [v["id"] for v in encargos]),
        estados=[e for e in ESTADOS_VENTA if e != "Anulada"], metodos=METODOS_PAGO, laboratorios=LABORATORIOS,
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
        total=sum(p["importe"] for p in pagos), hoy=date.today().isoformat(),
        cierre=db.execute("SELECT * FROM cierres WHERE dia = ?", (dia,)).fetchone(),
        cierres=db.execute("SELECT * FROM cierres ORDER BY dia DESC LIMIT 10").fetchall(),
    )


def resumen_del_dia(db, dia):
    """Números del día para el cierre: ventas, cobros por medio de pago y pendientes."""
    ventas = db.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS total FROM ventas"
        " WHERE estado != 'Anulada' AND date(fecha) = ?",
        (dia,),
    ).fetchone()
    anuladas = db.execute(
        "SELECT COUNT(*) FROM ventas WHERE estado = 'Anulada' AND date(fecha) = ?", (dia,)
    ).fetchone()[0]
    por_metodo = {m: 0 for m in METODOS_PAGO}
    devoluciones = 0
    for p in db.execute("SELECT metodo, importe FROM pagos WHERE date(fecha) = ?", (dia,)):
        por_metodo[p["metodo"]] = por_metodo.get(p["metodo"], 0) + p["importe"]
        if p["importe"] < 0:
            devoluciones += -p["importe"]
    # De lo cobrado hoy, cuánto es de ventas de días anteriores (saldos)
    saldos = db.execute(
        "SELECT COALESCE(SUM(p.importe), 0) FROM pagos p JOIN ventas v ON v.id = p.venta_id"
        " WHERE date(p.fecha) = ? AND date(v.fecha) < ? AND p.importe > 0",
        (dia, dia),
    ).fetchone()[0]
    pendiente = db.execute(
        """SELECT COALESCE(SUM(v.total - COALESCE((SELECT SUM(importe) FROM pagos WHERE venta_id = v.id), 0)), 0)
           FROM ventas v WHERE v.estado != 'Anulada' AND date(v.fecha) = ?""",
        (dia,),
    ).fetchone()[0]
    return {
        "num_ventas": ventas["n"], "total_ventas": ventas["total"], "anuladas": anuladas,
        "por_metodo": por_metodo, "total_cobrado": sum(por_metodo.values()),
        "devoluciones": devoluciones, "saldos_anteriores": saldos, "pendiente": pendiente,
        "efectivo": por_metodo.get("Efectivo", 0),
    }


@bp.route("/cierre", methods=["GET", "POST"])
def cierre():
    """Cierre del día: resumen, efectivo contado y registro del cierre."""
    db = get_db()
    dia = request.values.get("dia") or date.today().isoformat()
    resumen = resumen_del_dia(db, dia)
    guardado = db.execute("SELECT * FROM cierres WHERE dia = ?", (dia,)).fetchone()
    if request.method == "POST":
        texto = request.form.get("efectivo_contado", "").strip()
        try:
            contado = parse_importe(texto, None)
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("main.cierre", dia=dia))
        valores = (resumen["num_ventas"], resumen["total_ventas"], resumen["total_cobrado"],
                   json.dumps(resumen["por_metodo"], ensure_ascii=False), contado,
                   request.form.get("notas", "").strip())
        if guardado:
            db.execute(
                "UPDATE cierres SET cerrado = datetime('now', 'localtime'), num_ventas = ?, total_ventas = ?,"
                " total_cobrado = ?, por_metodo = ?, efectivo_contado = ?, notas = ? WHERE dia = ?",
                (*valores, dia),
            )
        else:
            db.execute(
                "INSERT INTO cierres (num_ventas, total_ventas, total_cobrado, por_metodo, efectivo_contado,"
                " notas, dia) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (*valores, dia),
            )
        db.commit()
        flash(f"Día {formato_fecha(dia)} cerrado.", "ok")
        return redirect(url_for("main.cierre", dia=dia))
    # ¿Hubo cobros después de cerrar? Entonces el cierre guardado quedó desactualizado
    desactualizado = bool(guardado) and (
        guardado["total_cobrado"] != resumen["total_cobrado"] or guardado["total_ventas"] != resumen["total_ventas"]
    )
    return render_template(
        "cierre.html", dia=dia, resumen=resumen, cierre=guardado, desactualizado=desactualizado,
        guardado_por_metodo=json.loads(guardado["por_metodo"]) if guardado else {},
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
